"""
Extends logging module from python to log an error and also modify given error message to be then raised.
"""

__autor__ = "Leon Eiböck"
__date__ = "16/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import logging
from pathlib import Path


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


def get_logger():
    """
    Sets up the logger
    :return: Returns logger object

    >>> logger = get_logger()
    >>> raise logger.alert(TypeError, "Test")
    Traceback (most recent call last):
    ...
    TypeError: Test
    """
    logging.setLoggerClass(LoggerAdapter)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s :: %(message)s")
    log_file = Path("logs/log.txt")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    return logger
