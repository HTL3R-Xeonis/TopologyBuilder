"""
TopologyBuilder: builds and deploys network topologies to GNS3/ESXi from
a YAML config file. Entry point for the `topologybuilder` console script.
"""

import sys

from loguru import logger

from src.cli import app, Settings, Verbosity

__autor__ = "Leon Eiböck"
__date__ = "21/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"


def main():

    logger.remove()
    file_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{file}:{line}</cyan> - "
        "<level>{message}</level>"
    )

    print_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> - "
        "<level>{message}</level>"
    )

    logger.add(
        Settings.LOG_FILE_PATH, format=file_format, level="INFO", rotation="10MB"
    )
    logger.add(sys.stdout, format=print_format)

    try:
        app()
    except Exception as e:
        logger.error(f"{type(e).__name__}: {e}")
        if Settings.VERBOSITY_LEVEL.level == Verbosity.DEBUG.level:
            raise e
        sys.exit(1)


if __name__ == "__main__":
    main()
