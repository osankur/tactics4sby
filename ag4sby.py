import argparse
import subprocess
import tempfile
from logger import logger, setup_logging
from pyosys import libyosys as ys  # type: ignore
from pathlib import Path
from cell_graph import CellGraph

# TODO replace workdir by a local directory and add -f option as in sby
workdir: str = tempfile.gettempdir()

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
    g = CellGraph(top_module)
    deps = g.get_module_dependency_graph()
    g.write_module_dependencies_to_dot(Path("/tmp/a.dot"))
    g.print_module_dependencies()
    # build_dependency_graph(top_module, design)
