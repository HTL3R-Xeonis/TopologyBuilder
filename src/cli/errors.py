"""Consistent CLI error output."""

from functools import wraps

import typer
from loguru import logger

from src.settings import Settings, Verbosity


def cli_errors(function):
    """
    Reports command outcomes and unexpected errors with a failing exit code.
    :param function: CLI command to wrap.
    :return: Wrapped command.
    """

    @wraps(function)
    def guarded(*args, **kwargs):
        """
        Runs a CLI command with consistent failure reporting.
        :param args: Positional command arguments.
        :param kwargs: Named command arguments.
        :return: Wrapped command result.
        :raises typer.Exit: If a command fails outside debug mode.
        :raises Exception: Re-raises command errors in debug mode.
        """
        try:
            result = function(*args, **kwargs)
        except typer.BadParameter as exc:
            logger.warning("Invalid argument for {}: {}", function.__name__, exc)
            raise
        except (typer.Exit, typer.Abort):
            raise
        except Exception as exc:
            logger.opt(exception=exc).error("Command failed: {}", function.__name__)
            if Settings.VERBOSITY_LEVEL == Verbosity.DEBUG:
                raise
            raise typer.Exit(code=1) from exc
        return result

    return guarded
