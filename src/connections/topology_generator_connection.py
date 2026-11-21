"""Client for the Generator Topology Generator API."""

import requests
from loguru import logger

from src.settings import Settings


class TopologyGeneratorConnection:
    """Requests topology configurations from the Mimyr service."""

    @staticmethod
    def generate_topology(prompt: str, url: str | None = None) -> dict:
        """
        Requests a topology YAML configuration from the LLM.
        :param prompt: Natural-language topology description.
        :param url: Optional generator API URL overriding the settings.
        :return: API result with valid, yaml, and warnings fields.
        :raises ValueError: If the prompt or API address is invalid.
        :raises TimeoutError: If the generator request times out.
        :raises RuntimeError: If the request or response fails.
        """
        base_url = url if url is not None else Settings.API.TOPOLOGY_GENERATOR_URL
        if not isinstance(base_url, str) or not base_url.strip().startswith(("http://", "https://")):
            raise ValueError("Configure an http(s) URL for the topology generator.")
        if not prompt.strip():
            raise ValueError("The topology description must not be empty.")

        base_url = base_url.strip().rstrip("/")
        logger.info(f"Requesting topology generation from {base_url}")
        try:
            response = requests.post(
                f"{base_url}/api/generate-topology",
                json={"prompt": prompt},
                timeout=Settings.API.GENERATOR.TOPOLOGY_GENERATOR_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            logger.error("Topology generation request timed out.")
            raise TimeoutError("Topology generation request timed out.") from exc
        except requests.RequestException as exc:
            logger.error("Topology generation request failed.")
            raise RuntimeError("Topology generation request failed.") from exc

        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError("Topology generator returned invalid JSON.") from exc
        if not isinstance(result, dict):
            raise TypeError("Topology generator returned an unexpected response.")
        return result
