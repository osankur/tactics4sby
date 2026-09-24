"""Tests for ag4sby."""

from pathlib import Path

import ag4sby
from logger import logger, setup_logging
from pyosys import libyosys as ys  # type: ignore

MODULE_DEP1_SV = Path(__file__).resolve().parent / "module_dep1.sv"
TOP = "main"


def test_contract():
    def cell_names(cells: list[ys.Cell]) -> str:
        """The names of ``cells``, sorted and comma separated."""
        return ", ".join(sorted(str(cell.name) for cell in cells)) or "(none)"

    setup_logging(verbosity=1)
    design = ag4sby.make_model([str(MODULE_DEP1_SV)], TOP, False)
    top = design.module(f"\\{TOP}")

    types = {str(cell.type) for cell in top.cells_.values()}
    assert "$assume" in types, "no assume cells left after design prep"
    assert "$assert" in types, "no assert cells left after design prep"

    graph = ag4sby.CellGraph(top)
    deps = graph.get_module_dependency_graph()
    s1 = top.cells_["\\s1"]
    s2 = top.cells_["\\s2"]
    assert s1 in deps[s2]
    for cell in graph._assert_cells:
        cell in deps[s1]
        cell in deps[s2]


if __name__ == "__main__":
    test_contract()
