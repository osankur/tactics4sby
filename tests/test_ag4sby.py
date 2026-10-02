from pathlib import Path
from pyosys import libyosys as ys  # type: ignore
import cell_graph
from logger import setup_logging
import configuration

cfg = configuration.Configuration(Path(__file__).resolve().parent, 0)
MODULE_DEP2_SV = Path(__file__).resolve().parent / "module_dep2.sv"
CYCLIC_DEP_SV = Path(__file__).resolve().parent / "cyclic.sv"
TOP = "main"


def test_dependency_graph():
    cfg.verbose_yosys = True
    design = cell_graph.make_model(
        (str(f"read_verilog -sv {MODULE_DEP2_SV}"),), TOP, False, cfg
    )
    top = design.module(f"\\{TOP}")

    types = {str(cell.type) for cell in top.cells_.values()}
    assert "$assume" in types, "no assume cells left after design prep"
    assert "$assert" in types, "no assert cells left after design prep"

    cgraph = cell_graph.CellGraph(top)
    dgraph = cgraph.get_module_dependency_graph()
    s1 = top.cells_["\\s1"]
    s2 = top.cells_["\\s2"]
    s3 = top.cells_["\\s3"]
    assert dgraph.deps[s1] == []
    assert {s1} == set(dgraph.deps[s2])
    assert {s2} == set(dgraph.deps[s3])


def test_cyclic_dependency_graph():
    design = cell_graph.make_model(
        (str(f"read_verilog -sv {CYCLIC_DEP_SV}"),), TOP, False, cfg
    )
    top = design.module(f"\\{TOP}")

    setup_logging(3)

    cgraph = cell_graph.CellGraph(top)
    dgraph = cgraph.get_module_dependency_graph()
    s1 = top.cells_["\\s1"]
    s2 = top.cells_["\\s2"]
    # Cycle is present:
    assert s1 in dgraph.deps[s2]
    assert s2 in dgraph.deps[s1]
    # An ordering can still be computed by removing one of the edges:
    topo = dgraph.get_topological_ordering()
    assert topo == [s2, s1]


if __name__ == "__main__":
    test_dependency_graph()
    test_cyclic_dependency_graph()
