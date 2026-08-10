"""
Client for the local Topology Generator API, which uses an LLM to produce a topology
config YAML from a natural-language prompt.
"""

__license__ = "GNU GPLv3"

import requests

from src.logger_adapter import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_URL = "http://10.20.20.172:8002"
DEFAULT_TIMEOUT_SECONDS = 1800  # generation can legitimately take a while on
# constrained hardware, across multiple Ollama servers/retries server-side


def generate_topology(
    prompt: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """
    Requests a topology config from the Topology Generator API for the given prompt.
    :param prompt: Natural-language description of the desired topology
    :param base_url: Base URL of the Topology Generator API
    :param timeout_seconds: how long to wait for a response before giving up.
        Should exceed the server's own request_timeout * max_retries, since a
        legitimate successful generation can take that long.
    :return: Parsed JSON response. Contains at least 'yaml', 'valid' and 'warnings'.
    """
    logger.info(f"Requesting topology generation from {base_url}")
    response = requests.post(
        f"{base_url}/api/generate-topology",
        json={"prompt": prompt},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.json()
