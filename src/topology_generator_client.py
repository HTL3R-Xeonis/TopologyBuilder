"""
Client for the local Topology Generator API, which uses an LLM to produce a topology
config YAML from a natural-language prompt.
"""

__autor__ = "Leon Eiböck"
__date__ = "08/08/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import requests

from src.logger_adapter import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_URL = "http://10.20.20.172:8002"


def generate_topology(prompt: str, base_url: str = DEFAULT_BASE_URL) -> dict:
    """
    Requests a topology config from the Topology Generator API for the given prompt.
    :param prompt: Natural-language description of the desired topology
    :param base_url: Base URL of the Topology Generator API
    :return: Parsed JSON response. Contains at least 'yaml', 'valid' and 'warnings'.
    """
    logger.info(f"Requesting topology generation from {base_url}")
    response = requests.post(
        f"{base_url}/api/generate-topology",
        json={"prompt": prompt},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()
