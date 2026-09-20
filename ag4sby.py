from collections.abc import Iterator
import itertools
import argparse
import subprocess
import tempfile
from logger import logger, setup_logging
from pyosys import libyosys as ys  # type: ignore
from pathlib import Path

from cell_io import cell_input_bits, cell_output_bits

# TODO replace workdir by a local directory and add -f option as in sby
workdir: str = tempfile.gettempdir()

Node = ys.Cell | ys.SigBit


class CellGraph:
    """
    Graph where nodes are sigbits or cells, and edges are connections linking these.

    Computes dependency graph linking the following subset of cells: submodules, assume and assert cells:
    we have c -> c' if there is sequence of sigbits (possibly going through other cells)
    from an output of cell c to an input of cell c'.
    """

    contract_assume_cells: set[ys.Cell]
    contract_assert_cells: set[ys.Cell]

    _topmodule: ys.Module
    _design: ys.Design
    _sigbit_to_driver_cell: dict[ys.SigBit, ys.Cell]
    _assume_cells: set[ys.Cell]
    _assert_cells: set[ys.Cell]
    _submodule_cells: set[ys.Cell]
    _sigmap: ys.SigMap

    _module_dependencies: dict[ys.Cell, set[ys.Cell]] | None

    #: fill/line colours used for the node kinds of the .dot export
    _DOT_NODE_STYLES: dict[str, str] = {
        "assume": 'fillcolor="#c8e6c9", color="#2e7d32"',  # green
        "module": 'fillcolor="#bbdefb", color="#1565c0"',  # blue
        "assert": 'fillcolor="#ffcdd2", color="#c62828"',  # red
    }

    def __init__(self, top_module: ys.Module, design: ys.Design):
        self._top_module = top_module
        self._design = design

        # All assume cells of top_module
        self._assume_cells = set()
        # All assert cells of top_module
        self._assert_cells = set()
        # All contract assume cells of top_module (subset of _assume_cells)
        self.contract_assume_cells = set()
        # All contract assert cells of top_module (subset of _assert_cells)
        self.contract_assert_cells = set()
        self._submodule_cells = set()
        self._module_dependencies = None
        module_names = set(design.modules_.keys())
        for cell in top_module.cells_.values():
            if cell.type == "$assert":
                self._assert_cells.add(cell)
            elif cell.type == "$assume":
                self._assume_cells.add(cell)
            elif cell.type in module_names:
                self._submodule_cells.add(cell)

        self._sigmap = ys.SigMap(top_module)
        self._sigbit_to_driver_cell = {
            bit: cell
            for cell in top_module.cells_.values()
            for _, bit in cell_output_bits(cell, self._sigmap)
        }
        self._compute_contract()

    """ Iterates over all cell and sigbits entering this node """

    def get_predecessors(self, node: Node) -> Iterator[Node]:
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

    def _visit_backwards(self, nodes: list[Node], collect, stop_at):
        """
        Recursively visits predecessors of nodes, yielding node if collect(node),
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

        for node in nodes:
            yield from _visit(node)

    """ Return the contract of the top_module, that is, a pair of cell lists (A,G)
        where A is the list of pure assume cells, and G the list of pure assert cells.
        An assume cell is pure iff it does not depend on:
            - module outputs
            - submodule outputs
            - FF or mem cells
            - anyinit or initstate cells
            - undriven wires
        An assert cell is pure iff it does not depend on:
            - module inputs
            - ... (same as above)
    """

    def _compute_contract(self):
        def is_input(node):
            return (
                isinstance(node, ys.SigBit) and node.is_wire() and node.wire.port_input
            )

        def is_output(node):
            return (
                isinstance(node, ys.SigBit) and node.is_wire() and node.wire.port_output
            )

        def is_forbidden_cell(node: Node, assume_mode: bool):
            # TODO Review this function
            if isinstance(node, ys.Cell):
                return (
                    node.is_builtin_ff()
                    or node.is_mem_cell()
                    or node.type in ["$anyinit", "$initstate"]
                )
            elif isinstance(node, ys.SigBit):
                if not node.is_wire():
                    return False
                if assume_mode:
                    return not is_input(node) and (
                        is_output(node) or node not in self._sigbit_to_driver_cell
                    )
                else:
                    return not is_output(node) and (
                        is_input(node) or node not in self._sigbit_to_driver_cell
                    )

        for cell in self._assume_cells:
            logger.debug("Exploring predecessors of assume cell %s", cell.name)
            forbidden_preds = set(
                self._visit_backwards(
                    list(cell.connections_["\\A"].bits()),
                    collect=(lambda node: is_forbidden_cell(node, assume_mode=True)),
                    stop_at=(lambda node: is_forbidden_cell(node, assume_mode=True)),
                )
            )
            if forbidden_preds:
                logger.warning(
                    f"Assume cell {cell.name} is not pure due to the following cell dependencies:"
                )
                for c in forbidden_preds:
                    logger.warning(f"\t{self.string_of_node(c)}")
            else:
                self.contract_assume_cells.add(cell)
        for cell in self._assert_cells:
            logger.debug("Exploring predecessors of assert cell %s", cell.name)
            forbidden_preds = set(
                self._visit_backwards(
                    list(cell.connections_["\\A"].bits()),
                    collect=lambda node: is_forbidden_cell(node, assume_mode=False),
                    stop_at=lambda node: is_output(node)
                    or is_forbidden_cell(node, assume_mode=False),
                )
            )
            if forbidden_preds:
                logger.warning(
                    f"Assert cell {cell.name} is not pure due to the following cell dependencies:"
                )
                for c in forbidden_preds:
                    logger.warning(f"\t{self.string_of_node(c)}")
            else:
                self.contract_assert_cells.add(cell)

    def get_module_dependency_graph(self) -> dict[ys.Cell, set[ys.Cell]]:
        if self._module_dependencies:
            return self._module_dependencies
        self._module_dependencies = dict()
        for cell in itertools.chain(self._submodule_cells, self.contract_assert_cells):
            # Get the sigbits of input signals of cell (discard if not a wire)
            input_sigspecs = [
                list(conn.bits()) if conn.is_wire() else None
                for (conn_name, conn) in cell.connections_.items()
                if cell.input(conn_name)
            ]
            flattened_input_sigspecs = [
                item
                for sigbit_vector in filter(lambda li: li, input_sigspecs)
                for item in sigbit_vector
            ]
            deps = set(
                self._visit_backwards(
                    flattened_input_sigspecs,
                    collect=lambda node: node in self._submodule_cells,
                    stop_at=lambda node: node in self._submodule_cells,
                )
            )
            self._module_dependencies[cell] = deps
        assert self._module_dependencies
        return self._module_dependencies

    def print_module_dependencies(self):
        if not self._module_dependencies:
            self.get_module_dependency_graph()
        assert self._module_dependencies
        for cell in self._module_dependencies:
            logger.info(f"{cell.name} depends on:")
            for dep_cell in self._module_dependencies[cell]:
                logger.info(f"\t{dep_cell}")

    def write_module_dependencies_to_dot(self, file: Path):
        """Write ``self._module_dependencies`` to ``file`` in Graphviz DOT format.

        The graph has one node per cell of the dependency graph.  Assume cells
        are aligned in the leftmost column (green), assert cells in the
        rightmost one (red), and the submodule instances in between (blue); an
        edge ``a -> b`` means that ``b`` depends on ``a``.
        """

        def _dot_kind(cell: ys.Cell) -> str:
            """Classify ``cell`` for the .dot export: assume, assert, or module."""
            if cell in self._assume_cells:
                return "assume"
            if cell in self._assert_cells:
                return "assert"
            return "module"

        def _dot_text(text: str) -> str:
            """Return ``text`` as a quoted DOT identifier/label."""
            return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

        if not self._module_dependencies:
            self.get_module_dependency_graph()
        dependencies = self._module_dependencies or {}

        nodes = {cell for cell, deps in dependencies.items() for cell in deps | {cell}}
        columns: dict[str, list[ys.Cell]] = {"assume": [], "module": [], "assert": []}
        for cell in sorted(nodes, key=lambda cell: str(cell.name)):
            columns[_dot_kind(cell)].append(cell)

        lines = [
            f"// module dependencies of {self._top_module.name}",
            "// generated by ag4sby; edge a -> b means: b depends on a",
            "digraph module_dependencies {",
            '\trankdir="LR";',
            f"\tgraph [label={_dot_text(f'module dependencies of {self._top_module.name}')},"
            ' labelloc="t", fontname="Helvetica"];',
            '\tnode [shape="box", style="rounded,filled", fontname="Helvetica"];',
            '\tedge [color="#616161"];',
        ]

        # forces the two side columns even if a cell has predecessors/successors
        # that would otherwise pull it towards the middle of the layout
        for kind, rank in (("assume", "min"), ("assert", "max")):
            if columns[kind]:
                same_rank = "; ".join(_dot_text(str(c.name)) for c in columns[kind])
                lines.append(f"\t{{rank={rank}; {same_rank};}}")

        lines.append("")
        for kind in ("assume", "module", "assert"):
            for cell in columns[kind]:
                name = _dot_text(str(cell.name))
                lines.append(f"\t{name} [label={name}, {self._DOT_NODE_STYLES[kind]}];")

        lines.append("")
        for cell in sorted(dependencies, key=lambda cell: str(cell.name)):
            for dep in sorted(dependencies[cell], key=lambda cell: str(cell.name)):
                lines.append(
                    f"\t{_dot_text(str(dep.name))} -> {_dot_text(str(cell.name))};"
                )

        lines.append("}")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("\n".join(lines) + "\n")
        logger.info("Wrote module dependency graph to %s", file)


def make_model(filenames: list[str], top: str, opt_multiclock: bool) -> ys.Design:
    global workdir
    modeldir = Path(workdir) / "model"
    modeldir.mkdir(exist_ok=True)

    with open(modeldir / "design_prep.ys", "w") as f:
        for file in filenames:
            if not file.endswith((".v", ".sv")):
                raise SystemExit(
                    f"error: unsupported file extension: {file} (only .v or .sv allowed)"
                )
            abs_path = Path(file).absolute()
            if file.endswith(".sv"):
                print(f"read_verilog -sv {abs_path}", file=f)
            else:
                print(f"read_verilog {abs_path}", file=f)
        print(f"hierarchy -smtcheck -top {top}", file=f)
        print("prep", file=f)
        print("scc -select; simplemap; select -clear", file=f)
        print("memory_nordff", file=f)
        if opt_multiclock:
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
        print(f"write_rtlil {modeldir}/design_prep.il", file=f)
        print(f"select -module \\{top}", file=f)
        print("show -format svg -prefix design_prep -stretch", file=f)

    subprocess.run(
        ["yosys", "-s", str(modeldir / "design_prep.ys")],
        stdout=None,
        stderr=None,
        check=True,
    )

    design = ys.Design()
    ys.run_pass(f"read_rtlil {modeldir}/design_prep.il", design)
    return design


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


if __name__ == "__main__":
    parser: argparse.ArgumentParser = parser_func()
    args: argparse.Namespace = parser.parse_args()
    setup_logging(
        verbosity=args.verbosity,
        log_file=args.log_file,
        use_color=args.log_color,
    )
    logger.info("Top module: %s", args.top)
    design: ys.Design = make_model(args.filenames, args.top, args.opt_multiclock)
    top_module = design.module(f"\\{args.top}")
    g = CellGraph(top_module, design)
    deps = g.get_module_dependency_graph()
    g.write_module_dependencies_to_dot(Path("/tmp/a.dot"))
    g.print_module_dependencies()
    # build_dependency_graph(top_module, design)
