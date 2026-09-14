"""Project-wide logging with exactly three levels: info, warning, error.

In development the console gets one line per event; when an error carries an
exception the line ends with a pointer to the log file, and only the rotating
file receives the full stacktrace. In production (`INFLUX_ENV=production`)
there is no file: everything, stacktraces included, goes to stderr so the
container runtime collects it. Call `setup_logging()` once at process start
and use `get_logger(__name__)` everywhere else.
"""

import logging
import logging.handlers
import sys
from typing import Any

from influx.core.config import INFLUX_ENV, LOG_BACKUP_COUNT, LOG_FILE, LOG_MAX_BYTES

_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Third-party loggers that chatter at INFO; only their warnings are worth seeing.
_NOISY_LOGGERS = ("crawlee", "httpx", "httpcore", "aiosqlite", "sqlalchemy", "asyncio")

_configured = False


class _ConsoleFormatter(logging.Formatter):
    """Same layout as the file, but never more than one line per event.

    Attached exceptions are dropped; so is everything after the first newline,
    since some libraries (Crawlee) paste tracebacks into the message itself.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        first_line, _, rest = message.partition("\n")
        if record.exc_info or record.exc_text or rest.strip():
            first_line = f"{first_line.rstrip()} — error occurred, check {LOG_FILE} for the full stacktrace"
        return f"{self.formatTime(record, _DATE_FORMAT)} {record.levelname:<7} {record.name}: {first_line}"


class Logger:
    """Thin facade over stdlib logging exposing only the three sanctioned levels."""

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def info(self, message: str, *args: Any) -> None:
        self._logger.info(message, *args)

    def warning(self, message: str, *args: Any) -> None:
        self._logger.warning(message, *args)

    def error(self, message: str, *args: Any, exc: BaseException | None = None) -> None:
        """Log an error. Inside an `except` block the active exception is attached
        automatically; pass `exc=` to attach one explicitly from anywhere else."""
        exc_info: Any = exc
        if exc is None and sys.exc_info()[0] is not None:
            exc_info = sys.exc_info()
        self._logger.error(message, *args, exc_info=exc_info)


def get_logger(name: str) -> Logger:
    return Logger(name)


def setup_logging() -> None:
    """Install the handlers on the root logger. Idempotent."""
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    for handler in _handlers():
        root.addHandler(handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _handlers() -> list[logging.Handler]:
    if INFLUX_ENV == "production":
        stderr = logging.StreamHandler(sys.stderr)
        stderr.setFormatter(logging.Formatter(_FILE_FORMAT, _DATE_FORMAT))
        return [stderr]

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(_ConsoleFormatter())
    file = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file.setFormatter(logging.Formatter(_FILE_FORMAT, _DATE_FORMAT))
    return [console, file]
