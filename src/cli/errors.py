"""Consistent CLI error output."""

from functools import wraps

import typer
from loguru import logger

from src.settings import Settings, Verbosity


def cli_errors(function):
    """Reports unexpected command errors with a failing exit code."""

    @wraps(function)
    def guarded(*args, **kwargs):
        """Runs a CLI command and reports failures."""
        try:
            return function(*args, **kwargs)
        except (typer.Exit, typer.Abort, typer.BadParameter):
            raise
        except Exception as exc:
            if Settings.VERBOSITY_LEVEL.level == Verbosity.DEBUG.level:
                raise
            logger.error(exc)
            raise typer.Exit(code=1) from exc

    return guarded
