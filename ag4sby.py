import sys
import os
import argparse
import traceback
from logger import logger, setup_logging
import parser
import sby_generator


def main(argv: list[str] | None = None) -> int:
    """Parse a proof strategy file and print a summary of it."""
    argparser = argparse.ArgumentParser(
        prog="proof_strategy",
        usage="%(prog)s [options] <strategy.json>",
        description="Parse a proof strategy JSON file and print a summary.",
    )
    argparser.add_argument("strategy", help="path to the proof strategy JSON file")
    argparser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
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
        "--multi-clock",
        action="store_true",
        dest="opt_multiclock",
        default=False,
        help="Multiclock",
    )
    argparser.add_argument(
        "-f",
        action="store_true",
        dest="force",
        help="remove workdir if it already exists",
    )
    argparser.add_argument(
        "-o",
        dest="out_file",
        help="Output .sby script file (default=stdout)",
        default=sys.stdout,
    )
    argparser.add_argument(
        "--verbose-yosys",
        action="store_true",
        dest="verbose_yosys",
        help="show output of yosys calls",
    )
    args = argparser.parse_args(argv)
    setup_logging(
        verbosity=args.verbosity,
        log_file=args.log_file,
        use_color=args.log_color,
    )
    initial_dir = os.getcwd()
    try:
        strategy = parser.parse_file(args.strategy)
        # like sby, paths inside the strategy file are relative to its directory
        os.chdir(os.path.dirname(os.path.abspath(args.strategy)))
        logger.info(parser._summarise(strategy))
        generator = sby_generator.SbyScript(
            strategy, args.verbosity > 0, args.verbose_yosys
        )
        if args.out_file is sys.stdout:
            generator.dump(sys.stdout)
        else:
            # -o is relative to the invocation directory, not the strategy dir
            os.chdir(initial_dir)
            with open(args.out_file, "w") as f:
                generator.dump(f)
    except Exception as exc:
        if args.verbosity > 1:
            traceback.print_exc()
        logger.error("%s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
