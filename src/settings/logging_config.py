"""Central logging configuration for TopologyBuilder."""

import sys
from pathlib import Path
from urllib.parse import urlsplit

from loguru import logger

from src.settings import Settings, Verbosity

FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {process.id} | {name}:{function}:{line} | {message}"
CONSOLE_FORMAT = "<level>{level: <8}</level> | <level>{message}</level>"


def safe_endpoint(url: str) -> str:
    """
    Returns an HTTP endpoint without credentials, query parameters or fragments.
    :param url: Original request URL.
    :return: Sanitized endpoint for diagnostic messages.
    :raises ValueError: If the URL contains an invalid port.
    """
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{host}{port}{parsed.path}"


def _console_filter(record: dict) -> bool:
    """
    Decides whether a record belongs on the interactive console.
    :param record: Loguru record with a severity level.
    :return: True when the current verbosity allows the record.
    """
    verbosity = Settings.VERBOSITY_LEVEL or Verbosity.NORMAL
    minimum = {
        Verbosity.QUIET: 40,
        Verbosity.NORMAL: 30,
        Verbosity.VERBOSE: 20,
        Verbosity.DEBUG: 10,
    }[verbosity]
    return record["level"].no >= minimum


def _file_filter(record: dict) -> bool:
    """
    Includes important activity by default and debug records in debug mode.
    :param record: Loguru record with a severity level.
    :return: True if the record belongs in the application log.
    """
    return record["level"].no >= (10 if Settings.VERBOSITY_LEVEL == Verbosity.DEBUG else 20)


def configure_logging() -> None:
    """
    Configures rotating activity and warning/error logs with console output.
    :raises OSError: If the log directories or files are inaccessible.
    :raises ValueError: If the log files have the same destination.
    """
    main_path = Path(Settings.LOG_FILE_PATH).expanduser()
    error_path = Path(Settings.ERROR_LOG_FILE_PATH).expanduser()
    if main_path.resolve() == error_path.resolve():
        raise ValueError("Main and error log files must have different paths.")
    main_path.parent.mkdir(parents=True, exist_ok=True)
    error_path.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()
    for path, level, sink_filter in (
        (main_path, "DEBUG", _file_filter),
        (error_path, "WARNING", None),
    ):
        logger.add(
            path,
            level=level,
            filter=sink_filter,
            format=FILE_FORMAT,
            rotation="10 MB",
            retention="14 days",
            encoding="utf-8",
            backtrace=False,
            diagnose=False,
            delay=False,
        )
    logger.add(
        sys.stderr,
        level="DEBUG",
        filter=_console_filter,
        format=CONSOLE_FORMAT,
        colorize=sys.stderr.isatty(),
        backtrace=False,
        diagnose=False,
    )
