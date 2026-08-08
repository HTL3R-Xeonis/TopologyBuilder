"""
Extends logging module from python to log an error and also modify given error message to be then raised.
Configures a package-wide logger hierarchy with a rotating file handler (always DEBUG) and a
console handler whose verbosity can be adjusted at runtime, e.g. from the CLI's --verbose flag.
"""

__autor__ = "Leon Eiböck"
__date__ = "16/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PACKAGE_LOGGER_NAME = "topologybuilder"
_DEFAULT_LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "log.txt"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 5


class LoggerAdapter(logging.Logger):
    is_test_run = False

    def alert(self, error: type[Exception], message: str) -> Exception:
        """
        Logs given error message and returns given exception with message.
        :param error: Exception to be modified
        :param message: Message to be logged
        :return: Modified exception

        >>> logger = get_logger()
        >>> raise logger.alert(TypeError, "Test")
        Traceback (most recent call last):
        ...
        TypeError: Test
        """
        if not self.is_test_run:
            self.error(f"[{error.__name__}] {message}")
        return error(message)


def _configure_package_logger() -> logging.Logger:
    """
    Sets up the package-wide 'topologybuilder' logger with a rotating file handler and a
    console handler. Idempotent: handlers are only attached once, even if called repeatedly
    across modules.
    :return: The configured package logger.
    """
    package_logger = logging.getLogger(_PACKAGE_LOGGER_NAME)
    if package_logger.handlers:
        return package_logger

    package_logger.setLevel(logging.DEBUG)
    package_logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)-8s - %(name)s :: %(message)s"
    )

    log_file = Path(os.getenv("TOPOLOGYBUILDER_LOG_FILE", str(_DEFAULT_LOG_FILE)))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    package_logger.addHandler(file_handler)

    console_level_name = os.getenv("TOPOLOGYBUILDER_LOG_LEVEL", "WARNING").upper()
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, console_level_name, logging.WARNING))
    console_handler.setFormatter(formatter)
    package_logger.addHandler(console_handler)

    return package_logger


def get_logger(name: str | None = None) -> LoggerAdapter:
    """
    Returns a logger nested under the 'topologybuilder' package logger.
    :param name: Usually the caller's __name__, used to identify the log source.
    :return: Configured logger instance.

    >>> logger = get_logger(__name__)
    >>> raise logger.alert(TypeError, "Test")
    Traceback (most recent call last):
    ...
    TypeError: Test
    """
    logging.setLoggerClass(LoggerAdapter)
    _configure_package_logger()
    logger_name = f"{_PACKAGE_LOGGER_NAME}.{name}" if name else _PACKAGE_LOGGER_NAME
    return logging.getLogger(logger_name)


def set_console_level(level: int) -> None:
    """
    Adjusts the verbosity of console output for the whole package, e.g. from the CLI's
    --verbose/--quiet flags. File logging is unaffected and always captures DEBUG and above.
    :param level: A logging level, e.g. logging.DEBUG or logging.INFO.
    """
    package_logger = _configure_package_logger()
    for handler in package_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, RotatingFileHandler
        ):
            handler.setLevel(level)
