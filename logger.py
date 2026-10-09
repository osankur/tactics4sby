import logging
import sys

LOGGER_NAME = "tactics4sby"

logging.setLoggerClass(logging.Logger)
logger = logging.getLogger(LOGGER_NAME)

# How many -v flags map to which level (index 0 == no -v given)
VERBOSITY_LEVELS: tuple[int, ...] = (logging.WARNING, logging.INFO, logging.DEBUG)

DEFAULT_LOG_FORMAT = "%(levelname)s: %(message)s"
VERBOSE_LOG_FORMAT = "%(levelname)s %(funcName)s:%(lineno)d: %(message)s"


class ColorFormatter(logging.Formatter):
    """Formatter that colours the level name when writing to a terminal."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def __init__(self, fmt=None, datefmt=None, use_color=True):
        super().__init__(fmt, datefmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname) if self.use_color else None
        if color:
            # work on a copy so other handlers see the untouched record
            record = logging.makeLogRecord(record.__dict__)
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    verbosity: int = 0,
    log_file: str | None = None,
    use_color: bool | None = None,
) -> logging.Logger:
    """Configure the tactics4sby logger.

    verbosity: number of -v flags; maps to WARNING/INFO/DEBUG/TRACE.
    level:     explicit level name or number; overrides verbosity.
    log_file:  also write log records to this file ('-' means stdout).
    use_color: colourise level names; default is auto-detect on the stream.
    """
    level = VERBOSITY_LEVELS[min(verbosity, len(VERBOSITY_LEVELS) - 1)]
    log_format = VERBOSE_LOG_FORMAT if verbosity else DEFAULT_LOG_FORMAT
    datefmt = None

    stream = sys.stdout if log_file == "-" else sys.stderr
    if use_color is None:
        use_color = stream.isatty()

    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False

    stream_handler = logging.StreamHandler(stream)
    stream_handler.setFormatter(ColorFormatter(log_format, datefmt, use_color))
    logger.addHandler(stream_handler)

    if log_file and log_file != "-":
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        # never colour when writing to a file
        file_handler.setFormatter(ColorFormatter(log_format, datefmt, False))
        logger.addHandler(file_handler)

    return logger
