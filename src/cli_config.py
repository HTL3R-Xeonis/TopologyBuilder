"""
Loads optional user-level default values for CLI options from a YAML config file.
"""

__autor__ = "Leon Eiböck"
__date__ = "08/08/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import os
from pathlib import Path
from typing import Any

import yaml

from src.logger_adapter import get_logger

logger = get_logger(__name__)

_DEFAULT_CONFIG_PATHS = (Path("./topologybuilder.yml"), Path("./topologybuilder.yaml"))


def load_cli_config() -> dict[str, Any]:
    """
    Loads CLI default values from a YAML config file, if one is found.
    Looks for, in order: the path in the TOPOLOGYBUILDER_CONFIG environment
    variable, then ./topologybuilder.yml, then ./topologybuilder.yaml.
    :return: Dict of config values, empty if no config file was found.
    """
    env_path = os.getenv("TOPOLOGYBUILDER_CONFIG")
    candidates = (Path(env_path),) if env_path else _DEFAULT_CONFIG_PATHS

    for path in candidates:
        if path.is_file():
            logger.debug(f"Loading CLI config from {path}")
            with open(path, "r") as file:
                return yaml.safe_load(file) or {}

    return {}
