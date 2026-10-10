import sys
import os
import shutil
import argparse
import traceback
from pathlib import Path
from logger import logger, setup_logging
import parser
import sby_generator
import configuration
import tempfile


def main(argv: list[str] | None = None) -> int:
    """Parse a proof strategy file and print a summary of it."""
    argparser = argparse.ArgumentParser(
        prog="tactics4sby",
        usage="%(prog)s [options] <strategy.json>",
        description="Produces a .sby configuration file from the given proof strategy file, runs sby, and reports results.",
    )
    argparser.add_argument("strategy", help="path to the proof strategy JSON file")
    argparser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=1,
        dest="verbosity",
        help="Increase verbosity: -v info, -vv debug",
    )
    argparser.add_argument(
        "--log-file",
        dest="log_file",
        default=None,
        help="Additionally write log records to FILE ('-' for stdout)",
    )
    argparser.add_argument(
        "--log-color",
        dest="log_color",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force or disable coloured log output (default: auto-detect)",
    )
    argparser.add_argument(
        "--dump-dot-circuits",
        action="store_true",
        dest="dump_dot_circuits",
        default=False,
        help="Let the sby script dump circuits in dot format",
    )
    argparser.add_argument(
        "--summarize",
        action="store_true",
        dest="summarize",
        default=False,
        help="Pretty print the proof strategy given as input",
    )
    argparser.add_argument(
        "--multi-clock",
        action="store_true",
        dest="opt_multiclock",
        default=False,
        help="Multiclock",
    )
    argparser.add_argument(
        "--verbose-yosys",
        action="store_true",
        dest="verbose_yosys",
        help="show output of yosys calls",
    )
    argparser.add_argument(
        "--verbose-sby",
        action="store_true",
        dest="verbose_sby",
        help="show output of sby calls",
    )
    argparser.add_argument(
        "--run-sby",
        action=argparse.BooleanOptionalAction,
        default=True,
        dest="run_sby",
        help="Run sby on produced .sby configuration file (use --no-run-sby to skip)",
    )
    argparser.add_argument(
        "--run-task",
        default=None,
        dest="run_task",
        help="Run only the given task (default: all tasks are run)",
    )
    argparser.add_argument(
        "-f",
        action="store_true",
        dest="force",
        help="remove workdir if it already exists",
    )
    argparser.add_argument(
        "--tmp-dir",
        default=None,
        dest="tmp_dir",
        help="custom tmp directory",
    )
    args = argparser.parse_args(argv)
    setup_logging(
        verbosity=args.verbosity,
        log_file=args.log_file,
        use_color=args.log_color,
    )
    try:
        strategy_path = Path(args.strategy).resolve()
        cfg = configuration.Configuration(strategy_path.parent, args.verbosity)
        cfg.verbose_sby = args.verbose_sby
        cfg.verbose_yosys = args.verbose_yosys
        cfg.dump_dot_circuits = args.dump_dot_circuits
        if args.tmp_dir:
            cfg.tmpdir = Path(args.tmp_dir) / strategy_path.stem
            if cfg.tmpdir.exists():
                if not args.force:
                    raise FileExistsError(
                        f"{args.tmp_dir} already exists; use -f to overwrite it"
                    )
                else:
                    shutil.rmtree(cfg.tmpdir)
        else:
            cfg.tmpdir = Path(tempfile.gettempdir()) / strategy_path.stem
            if cfg.tmpdir.exists():
                shutil.rmtree(cfg.tmpdir)
        cfg.tmpdir.mkdir(parents=True)
        os.chdir(cfg.basedir)
        strategy = parser.parse_file(strategy_path)
        if args.summarize:
            print(parser.summarize(strategy))
        sby_file = cfg.basedir / (strategy_path.stem + ".sby")
        generator = sby_generator.SbyGenerator(strategy, cfg)
        sby = generator.get_sby_script(sby_file)
        if sby_file.exists() and not args.force:
            raise FileExistsError(f"{sby_file} already exists; use -f to overwrite it")
        with open(sby_file, "w") as f:
            sby.dump(f)
        logger.info(f"Generated proof strategy into {sby_file}")
        if args.run_sby:
            sby.run(args.run_task)
        print(sby)
    except Exception as exc:
        if args.verbosity > 1:
            traceback.print_exc()
        logger.error("%s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
