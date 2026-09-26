import argparse
from logger import logger, setup_logging
from pathlib import Path
import proof_strategy

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
    # g = get_cell_graphs(args.filenames, args.top, args.opt_multiclock)
    # deps = g.get_module_dependency_graph()
    # g.write_module_dependencies_to_dot(Path("/tmp/a.dot"))
    # g.print_module_dependencies()