"""
Client for the Topology Generator API, which uses an LLM to produce a
topology config YAML from a natural-language prompt.
"""

__license__ = "GNU GPLv3"

import requests
from loguru import logger

from src.settings import Settings


class TopologyGeneratorClient:
    """
    Talks to the Topology Generator API.
    """

    @staticmethod
    def generate_topology(prompt: str) -> dict:
        """
        Requests a topology config from the Topology Generator API for the
        given prompt.
        :param prompt: natural-language description of the desired topology
        :return: parsed JSON response, containing at least 'yaml', 'valid',
            and 'warnings'
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the request itself fails.
        """
        logger.info(
            f"Requesting topology generation from {Settings.API.TOPOLOGY_GENERATOR_URL}"
        )
        try:
            response = requests.post(
                f"{Settings.API.TOPOLOGY_GENERATOR_URL}/api/generate-topology",
                json={"prompt": prompt},
                timeout=Settings.API.TOPOLOGY_GENERATOR_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.Timeout as err:
            logger.error(msg := "Topology generation request timed out.")
            raise TimeoutError(msg) from err
        except requests.RequestException as exc:
            logger.error(msg := "Topology generation request failed.")
            raise RuntimeError(msg) from exc
        return response.json()
