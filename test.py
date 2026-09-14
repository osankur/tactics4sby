from pyosys import libyosys as ys  # type: ignore

top = "acyclic"
file = top + ".sv"
design = ys.Design()
ys.run_pass(f"read_verilog -sv {file}", design)
ys.run_pass(f"hierarchy -top {top}", design)
ys.run_pass("prep", design)
module = design.module("\\acyclic")
