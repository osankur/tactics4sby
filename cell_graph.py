from dataclasses import dataclass
from collections.abc import Iterator
import itertools
from pathlib import Path

from pyosys import libyosys as ys  # type: ignore
from cell_io import cell_input_bits, cell_output_bits
from logger import logger
import proof_strategy

Node = ys.Cell | ys.SigBit

class CellGraph:
    """
    Graph where nodes are sigbits or cells, and edges are connections linking these.

    Computes dependency graph linking the following subset of cells: submodules, assume and assert cells:
    we have c -> c' if there is sequence of sigbits (possibly going through other cells)
    from an output of cell c to an input of cell c'.
    """

    contract_assume_cells: list[ys.Cell]
    contract_assert_cells: list[ys.Cell]

    _topmodule: ys.Module
    _sigbit_to_driver_cell: dict[ys.SigBit, ys.Cell]
    _assume_cells: set[ys.Cell]
    _assert_cells: set[ys.Cell]
    _submodule_cells: set[ys.Cell]
    _sigmap: ys.SigMap

    _module_dependencies: dict[ys.Cell, set[ys.Cell]] | None
    _module_contract_mask : proof_strategy.ModuleContract

    #: fill/line colours used for the node kinds of the .dot export
    _DOT_NODE_STYLES: dict[str, str] = {
        "assume": 'fillcolor="#c8e6c9", color="#2e7d32"',  # green
        "module": 'fillcolor="#bbdefb", color="#1565c0"',  # blue
        "assert": 'fillcolor="#ffcdd2", color="#c62828"',  # red
    }

    def __init__(self, top_module: ys.Module):
        self._top_module = top_module

        # All assume cells of top_module
        self._assume_cells = set()
        # All assert cells of top_module
        self._assert_cells = set()
        self._submodule_cells = set()
        self._module_dependencies = None
        self._module_contract_mask = proof_strategy.ModuleContract()
        module_names = set(top_module.design.modules_.keys())
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

    def get_predecessors(self, node: Node) -> Iterator[Node]:
        """ Iterates over all cell and sigbits entering this node """
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

    def get_module_dependency_graph(self, moduleContractMask = proof_strategy.ModuleContract()) -> dict[ys.Cell, set[ys.Cell]]:
        """ Return the dependency graph between submodule instances and asserts.
            Restrict the assume and asserts to the given mask.
        """
        if self._module_dependencies and self._module_contract_mask == moduleContractMask:
            return self._module_dependencies

        self._module_contract_mask = moduleContractMask
        if moduleContractMask.assumes:
            assert set(moduleContractMask.assumes).issubset(set(cell.name for cell in self._assume_cells))
            self.contract_assume_cells = [cell for cell in self._assume_cells if cell.name in moduleContractMask.assumes]
        else:
            self.contract_assume_cells = list(self._assume_cells)
        
        if moduleContractMask.asserts:
            assert set(moduleContractMask.asserts).issubset(set(cell.name for cell in self._assert_cells))
            self.contract_assert_cells = [cell for cell in self._assert_cells if cell.name in moduleContractMask.asserts]
        else:
            self.contract_assert_cells = list(self._assert_cells)

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


