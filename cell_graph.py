import subprocess
import tempfile
from dataclasses import dataclass
from collections.abc import Iterator
import itertools
from pathlib import Path

from pyosys import libyosys as ys  # type: ignore
from cell_io import cell_input_bits, cell_output_bits
from logger import logger
import proof_strategy

workdir: str = tempfile.gettempdir()


def _strip_backslash(id) -> str:
    assert id[0] == "\\", f"{id} does not start with a \\"
    return str(id)[1:]


def make_model(
    read_commands: tuple[str, ...],
    top: str,
    opt_multiclock: bool,
    verbose: bool = False,
    dump_dot: bool = True,
) -> ys.Design:
    global workdir
    modeldir = Path(workdir) / "model"
    modeldir.mkdir(exist_ok=True)

    with open(modeldir / "design_prep.ys", "w") as f:
        for cmd in read_commands:
            print(cmd, file=f)
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
        print(f"write_rtlil {modeldir}/{top}.il", file=f)
        if dump_dot:
            print(f"select -module \\{top}", file=f)
            print(f"show -format svg -prefix {top} -stretch", file=f)

    subprocess.run(
        ["yosys", "-s", str(modeldir / "design_prep.ys")],
        stdout=None if verbose else subprocess.DEVNULL,
        stderr=None if verbose else subprocess.DEVNULL,
        check=True,
    )
    design = ys.Design()
    ys.run_pass(f"read_rtlil {modeldir}/{top}.il", design)
    return design


Node = ys.Cell | ys.SigBit


@dataclass
class ModuleDependencyGraph:
    deps: dict[ys.Cell, list[ys.Cell]]

    def get_topological_ordering(self) -> list[ys.Cell]:
        """Returns a best-effort topological ordering of the graph.
        If the graph contains cycles, back edges during DFS are removed and reported as a warning.
        """
        # successors[u] = { v | u -> v }, i.e. the cells that depend on u
        successors: dict[ys.Cell, set[ys.Cell]] = {v: set() for v in self.deps}
        for v, preds in self.deps.items():
            for u in preds:
                successors.setdefault(u, set()).add(v)

        # 0 = unvisited, 1 = on the DFS stack, 2 = finished
        state: dict[ys.Cell, int] = {}
        postorder: list[ys.Cell] = []
        removed: set[tuple[ys.Cell, ys.Cell]] = set()

        def _visit(node: ys.Cell):
            state[node] = 1
            for succ in successors[node]:
                if state.get(succ, 0) == 1:
                    # back edge: succ is an ancestor of node on the DFS stack
                    removed.add((node, succ))
                    logger.warning(
                        f"Removing submodule dependency {node.name} -> {succ.name} for applying assume-guarantee rule"
                    )
                elif state.get(succ, 0) == 0:
                    _visit(succ)
            state[node] = 2
            postorder.append(node)

        for node in successors:
            if state.get(node, 0) == 0:
                _visit(node)

        # self.deps = {
        #     v: [u for u in preds if (u, v) not in removed]
        #     for v, preds in self.deps.items()
        # }
        postorder.reverse()
        return postorder


class CellGraph:
    """
    Graph where nodes are sigbits or cells, and edges are connections linking these.

    Computes dependency graph linking the following subset of cells: submodules, assume and assert cells:
    we have c -> c' if there is sequence of sigbits (possibly going through other cells)
    from an output of cell c to an input of cell c'.
    """

    top_module: ys.Module
    design: ys.Design
    _sigbit_to_driver_cell: dict[ys.SigBit, ys.Cell]
    assume_cells: set[ys.Cell]
    assert_cells: set[ys.Cell]
    submodule_instance_cells: set[ys.Cell]
    _sigmap: ys.SigMap

    _module_dependencies: dict[ys.Cell, set[ys.Cell]] | None
    _module_contract_mask: proof_strategy.ModuleContract

    #: fill/line colours used for the node kinds of the .dot export
    _DOT_NODE_STYLES: dict[str, str] = {
        "assume": 'fillcolor="#c8e6c9", color="#2e7d32"',  # green
        "module": 'fillcolor="#bbdefb", color="#1565c0"',  # blue
        "assert": 'fillcolor="#ffcdd2", color="#c62828"',  # red
    }

    def __init__(self, top_module: ys.Module, design: ys.Design):
        self.design = design
        self.top_module = top_module

        # All assume cells of top_module
        self.assume_cells = set()
        # All assert cells of top_module
        self.assert_cells = set()
        self.submodule_instance_cells = set()
        self._module_dependencies = None
        self._module_contract_mask = proof_strategy.ModuleContract()
        module_names = set(top_module.design.modules_.keys())
        for cell in top_module.cells_.values():
            if cell.type == "$assert":
                self.assert_cells.add(cell)
            elif cell.type == "$assume":
                self.assume_cells.add(cell)
            elif cell.type in module_names:
                self.submodule_instance_cells.add(cell)
        self._sigmap = ys.SigMap(top_module)
        self._sigbit_to_driver_cell = {
            bit: cell
            for cell in top_module.cells_.values()
            for _, bit in cell_output_bits(cell, self._sigmap)
        }

    def get_predecessors(self, node: Node) -> Iterator[Node]:
        """Iterates over all cell and sigbits entering this node"""
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
                # logger.debug("visiting %s", self.string_of_node(node))
                if collect(node):
                    yield node
                if not stop_at(node):
                    for pnode in self.get_predecessors(node):
                        yield from _visit(pnode)

        for node in nodes:
            yield from _visit(node)

    def get_module_dependency_graph(
        self, participating_instances: None | set[str] = None
    ) -> ModuleDependencyGraph:
        """Return the dependency graph between submodule instances and asserts.
        Restrict the assume and asserts to the given tuples when not None.

        ``participating_instances`` is an optional set of submodule instance or assert names (without backslash) to consider in this graph.
        """
        if participating_instances is None:
            instance_cells = self.submodule_instance_cells
        else:
            instance_cells = set(
                cell
                for cell in itertools.chain(
                    self.submodule_instance_cells, self.assert_cells
                )
                if _strip_backslash(cell.name) in participating_instances
            )
        deps = dict()
        for cell in itertools.chain(instance_cells):
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
            cell_deps: list[ys.Cell] = list(
                self._visit_backwards(
                    flattened_input_sigspecs,
                    collect=lambda node: node in instance_cells,
                    stop_at=lambda node: node in instance_cells,
                )
            )
            deps[cell] = cell_deps
        return ModuleDependencyGraph(deps)

    def print_module_dependencies(self):
        g = self.get_module_dependency_graph()
        for cell in g.deps:
            logger.info(f"{cell.name} depends on:")
            for dep_cell in g.deps[cell]:
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
            if cell in self.assume_cells:
                return "assume"
            if cell in self.assert_cells:
                return "assert"
            return "module"

        def _dot_text(text: str) -> str:
            """Return ``text`` as a quoted DOT identifier/label."""
            return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

        dependencies = self.get_module_dependency_graph()

        nodes = {
            cell
            for cell, deps in dependencies.deps.items()
            for cell in itertools.chain(deps, [cell])
        }
        columns: dict[str, list[ys.Cell]] = {"assume": [], "module": [], "assert": []}
        for cell in sorted(nodes, key=lambda cell: str(cell.name)):
            columns[_dot_kind(cell)].append(cell)

        lines = [
            f"// module dependencies of {self.top_module.name}",
            "// generated by ag4sby; edge a -> b means: b depends on a",
            "digraph module_dependencies {",
            '\trankdir="LR";',
            f"\tgraph [label={_dot_text(f'module dependencies of {self.top_module.name}')},"
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
        for cell in sorted(dependencies.deps, key=lambda cell: str(cell.name)):
            for dep in sorted(dependencies.deps[cell], key=lambda cell: str(cell.name)):
                lines.append(
                    f"\t{_dot_text(str(dep.name))} -> {_dot_text(str(cell.name))};"
                )

        lines.append("}")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("\n".join(lines) + "\n")
        logger.info("Wrote module dependency graph to %s", file)


def get_cell_graphs(
    read_commands: tuple[str, ...],
    top: str,
    opt_multiclock: bool,
    verbose: bool = False,
) -> dict[str, CellGraph]:
    design: ys.Design = make_model(read_commands, top, opt_multiclock, verbose)
    return {
        _strip_backslash(str(name)): CellGraph(module, design)
        for name, module in design.modules_.items()
    }
