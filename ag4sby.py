import argparse
import subprocess
import sys
import tempfile
from pyosys import libyosys as ys  # type: ignore
from pathlib import Path

# TODO replace workdir by a local directory and add -f option as in sby
workdir: str = tempfile.gettempdir()
input_files = []
verbose = False


def parser_func() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ag4sby", usage="%(prog)s [<filename>]+")
    parser.set_defaults(exe_paths=dict())
    parser.add_argument("filenames", nargs="+", help="list of input file names")
    parser.add_argument(
        "-top", dest="top", required=True, help="Name of the top module"
    )
    parser.add_argument("-v", action="store_true", dest="verbose", help="Verbose")
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


def build_dependency_graph(top_module: ys.Module, design: ys.Design):
    """ """
    # deps = {module: [] for module in design.modules_}
    # Add all assert and assume cells of the top module as nodes to the dependency graph
    # Make graph traversal for each objective in deps
    module_names = list(design.modules_.keys())
    top_assume_cells = []
    top_assert_cells = []
    submodule_cells = []
    for cell in top_module.cells_.values():
        if cell.type == "$assert":
            top_assert_cells.append(cell)
        elif cell.type == "$assume":
            top_assume_cells.append(cell)
        elif cell.type in module_names:
            submodule_cells.append(cell)
    print(top_assume_cells)
    print(top_assert_cells)
    print(submodule_cells)
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
            if file.endswith(".sv"):
                print(f"read_verilog -sv {file}", file=f)
            else:
                print(f"read_verilog {file}", file=f)
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
    design: ys.Design = make_model(args)
    top_module = design.module(f"\{args.top}")
    build_dependency_graph(top_module, design)


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
