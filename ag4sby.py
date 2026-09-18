from collections.abc import Iterator
import itertools
import argparse
import subprocess
import tempfile
from logger import logger, setup_logging
from pyosys import libyosys as ys  # type: ignore
from pathlib import Path

from cell_io import cell_input_bits, cell_output_bits, cell_inputs

# TODO replace workdir by a local directory and add -f option as in sby
workdir: str = tempfile.gettempdir()

Node = ys.Cell | ys.SigBit


def parser_func() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ag4sby", usage="%(prog)s [<filename>]+")
    parser.set_defaults(exe_paths=dict())
    parser.add_argument("filenames", nargs="+", help="list of input file names")
    parser.add_argument(
        "-top", dest="top", required=True, help="Name of the top module"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        dest="verbosity",
        help="Increase verbosity: -v info, -vv debug, -vvv trace",
    )
    parser.add_argument(
        "--log-file",
        dest="log_file",
        default=None,
        help="Additionally write log records to FILE ('-' for stdout)",
    )
    parser.add_argument(
        "--log-color",
        dest="log_color",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force or disable coloured log output (default: auto-detect)",
    )
    parser.add_argument(
        "--multi-clock",
        action="store_true",
        dest="opt_multiclock",
        default=False,
        help="Multiclock",
    )
    parser.add_argument(
        "-f",
        action="store_true",
        dest="force",
        help="remove workdir if it already exists",
    )
    return parser

def get_contract(module : ys.Module):
    def is_assume_cell_contract(assume_cell: ys.Cell):
        """Whether the assume cell only depends on its module inputs:
        In particular, this is false if any wire comes from a submodule cell or an FF."""
        # TODO
        return True

    def is_assert_cell_contract(assume_cell: ys.Cell):
        """Whether the assume cell only depends on its module outputs"""
        # TODO
        return True

    # TODO

class DependencyGraph:
    """
    Graph linking submodule, assume, and assert cells:
    we have c -> c' if there is sequence of sigbits (possibly going through other cells)
    from an output of c to an input of c'.
    """
    topmodule: ys.Module
    design: ys.Design
    _sigbit_to_driver_cell: dict[ys.SigBit, ys.Cell]
    assume_cells: set[ys.Cell]
    assert_cells: set[ys.Cell]
    submodule_cells: set[ys.Cell]
    # Module inputs that are constrained by a top assume cell
    assumed_inputs: set[ys.SigBit]

    dependencies: dict[ys.Cell, set[ys.Cell]]

    def __init__(self, top_module: ys.Module, design: ys.Design):
        self.top_module = top_module
        self.design = design
        
        self.assume_cells = set()
        self.assert_cells = set()
        self.submodule_cells = set()
        self.assumed_inputs = set()
        self.dependencies = dict()
        module_names = set(design.modules_.keys())
        for cell in top_module.cells_.values():
            if cell.type == "$assert":
                self.assert_cells.add(cell)
            elif cell.type == "$assume":
                self.assume_cells.add(cell)
            elif cell.type in module_names:
                self.submodule_cells.add(cell)

        self.sigmap = ys.SigMap(top_module)
        self._sigbit_to_driver_cell = {
            bit: cell
            for cell in top_module.cells_.values()
            for _, bit in cell_output_bits(cell, self.sigmap)
        }
        self._build_dependency_graph()

    def get_predecessors(
        self, node: Node
    ) -> Iterator[Node]:
        if isinstance(node, ys.Cell):
            for _, sigbit in cell_input_bits(node):
                yield sigbit
        elif isinstance(node, ys.SigBit):
            # None for an input or other non-driven wire or a constant
            driver = self._sigbit_to_driver_cell.get(node, None)
            if driver is not None:
                yield driver
        else:
            raise Exception(f"graph node of type {type(node)} encountered")

    def string_of_node(self, node: Node):
        if isinstance(node, ys.Cell):
            return node.name
        elif isinstance(node, ys.SigBit):
            if node.is_wire():
                return f"{node.wire.name}[{node.offset}]"
            else:
                return f"{node.data}"
        else:
            return None

    def _visit_backwards(self, node: Node, collect, stop_at):
        """
        Recursively visits predecessors of node, yielding node if collect(node),
        and cutting the search branch at node if stop_at(node).
        """
        visited = set()

        def _visit(node: Node):
            if node not in visited:
                visited.add(node)
                logger.debug("visiting %s", self.string_of_node(node))
                if collect(node):
                    yield node
                if not stop_at(node):
                    for pnode in self.get_predecessors(node):
                        yield from _visit(pnode)

        yield from _visit(node)

    def _build_dependency_graph(self):
        """Explore through predecessors from each sub module, and assert cells;
        stop at cells of interest."""

        # Find module inputs that are constrained by assume cells
        def is_input(node):
            return (
                isinstance(node, ys.SigBit) and node.is_wire() and node.wire.port_input
            )

        for assume_cell in self.assume_cells:
            logger.debug("exploring assume cell %s", assume_cell.name)
            self.assumed_inputs |= set(
                self._visit_backwards(
                    assume_cell,
                    collect=is_input,
                    stop_at=lambda node: node in self.submodule_cells,
                )
            )
        logger.info("Assumed inputs:")
        for inp in self.assumed_inputs:
            logger.info("\t%s", self.string_of_node(inp))
        for cell in itertools.chain(self.submodule_cells, self.assert_cells):
            deps  = set(
                self._visit_backwards(
                    cell,
                    collect=lambda node: node in self.submodule_cells or node in self.assumed_inputs,
                    stop_at=lambda node: node in self.submodule_cells,
                )
            )

        return None


def make_model(args: argparse.Namespace) -> ys.Design:
    global workdir
    modeldir = Path(workdir) / "model"
    modeldir.mkdir(exist_ok=True)

    with open(modeldir / "design_prep.ys", "w") as f:
        for file in args.filenames:
            if not file.endswith((".v", ".sv")):
                raise SystemExit(
                    f"error: unsupported file extension: {file} (only .v or .sv allowed)"
                )
            abs_path = Path(file).absolute()
            if file.endswith(".sv"):
                print(f"read_verilog -sv {abs_path}", file=f)
            else:
                print(f"read_verilog {abs_path}", file=f)
        print(f"hierarchy -smtcheck -top {args.top}", file=f)
        print("prep", file=f)
        print("scc -select; simplemap; select -clear", file=f)
        print("memory_nordff", file=f)
        if args.opt_multiclock:
            print("clk2fflogic", file=f)
        else:
            print("async2sync", file=f)
        print("opt_clean", file=f)
        print("formalff -setundef -clk2ff -ff2anyinit -hierarchy", file=f)
        # we only keep assume and asserts
        print("chformal -live -fair -cover -remove", file=f)
        print("opt_clean", file=f)
        print("check", file=f)  # can't detect undriven wires past this point
        print("setundef -undriven -anyseq", file=f)
        print("opt -fast", file=f)
        print("rename -witness", file=f)
        print("opt_clean", file=f)
        print(f"""write_rtlil {modeldir}/design_prep.il""", file=f)

    subprocess.run(
        ["yosys", "-s", str(modeldir / "design_prep.ys")],
        stdout=None,
        stderr=None,
        check=True,
    )

    design = ys.Design()
    ys.run_pass(f"read_rtlil {modeldir}/design_prep.il", design)
    return design


if __name__ == "__main__":
    parser: argparse.ArgumentParser = parser_func()
    args: argparse.Namespace = parser.parse_args()
    setup_logging(
        verbosity=args.verbosity,
        log_file=args.log_file,
        use_color=args.log_color,
    )
    logger.info("Top module: %s", args.top)
    design: ys.Design = make_model(args)
    top_module = design.module(f"\{args.top}")
    DependencyGraph(top_module, design)
    # build_dependency_graph(top_module, design)


def _dump_sigbit(bit):
    if bit.is_wire():
        if bit.wire.width == 1:
            return bit.wire.name.str()
        else:
            return f"{bit.wire.name} [{bit.offset}]"
    else:
        if bit.data == ys.State.S1:
            return 1
        elif bit.data == ys.State.S0:
            return 0
        else:
            assert "unknown constants not supported"


def print_connections(connections):
    for conn_from, conn_to in connections:
        for bit_from, bit_to in zip(conn_from, conn_to):
            # print(f"{bit_from} -> {bit_to}")
            print(f"assign {_dump_sigbit(bit_from)} = {_dump_sigbit(bit_to)};")


# print("* Module connections")
# print_connections(module.connections_)
# for c in module.cells_.values():
#   print(f"Printing connections of {c.name}")
#   print_connections(c.connections_)
#   print("\n")

# print("* Cell Connections:")
# c = module.cell("$ternary$acyclic.sv:9$6")
# conns = c.connections_.values()
# for conn in conns:
#     print(f"Connection {conn}")
#     for b in conn:
#         print(f"Bit {b} is_wire: {b.is_wire()} {b.wire} {b.data}")
# for (cname, ccon) in c.connections_.items():
#     print((cname, ccon))
# print(ccon.Representation)
# print(list(c.connections_))
# for conn_from, conn_to in c.connections_:
#     print(f"{conn_from} -> {conn_to}")
# for bit_from, bit_to in zip(conn_from, conn_to):
#   print(f"{bit_from} -> {bit_to}")s
