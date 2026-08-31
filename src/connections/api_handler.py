import json
import tarfile
from typing import Set

import requests
from loguru import logger

from src.settings import Settings
from .generic_connection import GenericConnection

_OVA_DOWNLOAD_CHUNK_SIZE = 8 * 1024 * 1024
_OVA_DOWNLOAD_MAX_ATTEMPTS = 3


class APIHandler:
    """
    Base class for API methods.
    """

    def __init__(self, ip: str, port: int):
        """
        :param ip: IP address of the API server
        :param port: Port of the API server
        :raises ValueError: Is thrown when the IPv4 address is not a public, private or loopback address.
        :raises TypeError: Is thrown when the parameters are of the wrong types.
        """
        if not isinstance(ip, str) or not isinstance(port, int):
            raise TypeError

        if not GenericConnection.is_valid_ipv4_address(ip):
            logger.error(msg := f"Invalid IPv4 address: {ip}")
            raise ValueError(msg)

        self.ip = ip
        self.port = port

    @staticmethod
    def get(url: str, parsing_method: str = "json", **kwargs) -> dict | None:
        """
        General method to make an API GET request
        :param parsing_method: Method of parsing the response.
        :param url: url to the API endpoint
        :param kwargs: Keyword arguments for the get request.
        :return: The parsed response from the GET request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the response is not parseable to JSON.
        """
        try:
            response = requests.get(url, timeout=5, **kwargs)
            response.raise_for_status()
            return APIHandler.parse_response(response, parsing_method)
        except requests.Timeout:
            logger.error(msg := f"GET request timed out to: {url}")
            raise TimeoutError(msg)
        except requests.HTTPError as err:
            logger.error(msg := f"GET request failed: {url}. Exception: {err}")
            raise

    @staticmethod
    def post(url: str, parsing_method: str = "json", **kwargs) -> dict | None:
        """
        General method to make an API POST request
        :param url: url to the API endpoint
        :param parsing_method: Method of parsing the response.
        :param kwargs: Keyword arguments for the post request.
        :return: The parsed response from the POST request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the response is not parseable to JSON.
        """
        try:
            # @TODO ADD TIMEOUT. CURRENTLY RUNS INTO ERROR WHILST DEPLOYING VM. PERIODICALL RESPONSES FROM API SERVER ARE MISSING.
            response = requests.post(url, **kwargs)
            response.raise_for_status()
            return APIHandler.parse_response(response, parsing_method)
        except requests.Timeout:
            logger.error(msg := f"POST request timed out to: {url}")
            raise TimeoutError(msg)
        except requests.HTTPError as err:
            logger.error(msg := f"POST request failed: {url}. Exception: {err}")
            raise

    @staticmethod
    def delete(url: str, parsing_method: str = "json", **kwargs) -> dict | None:
        """
        General method to make an API DELETE request
        :param url: url to the API endpoint
        :param parsing_method: Method of parsing the response.
        :param kwargs: Keyword arguments for the delete request.
        :return: The parsed response from the DELETE request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the response is not parseable to JSON.
        """
        try:
            response = requests.delete(url, timeout=5, **kwargs)
            response.raise_for_status()
            return APIHandler.parse_response(response, parsing_method)
        except requests.Timeout:
            logger.error(msg := f"DELETE request timed out to: {url}")
            raise TimeoutError(msg)
        except requests.HTTPError as err:
            logger.error(msg := f"DELETE request failed: {url}. Exception: {err}")
            raise

    @staticmethod
    def parse_response(
        response: requests.Response, parsing_method: str = "json"
    ) -> None | dict:
        """
        Parses the HTTP response as wanted.
        :param response: Response from the HTTP request.
        :param parsing_method: Method of parsing the response.
        :return: method: ``json`` -> return dict. else None
        :raises JSONDecodeError: Is thrown when the response is not parseable to JSON.
        """
        if response.status_code == 204:
            return None
        try:
            if parsing_method == "json":
                return response.json()
            return NotImplemented
        except json.decoder.JSONDecodeError as e:
            logger.error(
                "An error occurred trying to parse the response to using json: " + e.msg
            )
            raise

    @staticmethod
    def get_esxi_template_names() -> Set[str]:
        """
        Returns a set of available template names for ESXi.
        :return: The set containing received template names.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        if Settings.API.LITERAL_API_VALUES:
            return Settings.API.LITERAL_ESXI_TEMPLATES
        data = APIHandler.get(f"{Settings.API.ESXI_TEMPLATE_SERVER_URL}/api/templates")
        return {template["name"] for template in data["templates"]}

    @staticmethod
    def download_ova(template_name: str, dest_path: str) -> None:
        """
        Downloads the OVA file for the NFS-share template best matching
        ``template_name`` to ``dest_path``, streamed in chunks since these
        files run into multiple gigabytes.

        The proxy's upstream connection to the NFS share has been observed
        to drop mid-transfer without that surfacing as an HTTP-level error -
        the response still looks like a normal 200 completion, just with a
        truncated body. Every download is verified to be a structurally
        complete tar archive before being accepted, with a few retries
        since this has been observed to be intermittent.
        :param template_name: template name to search for, e.g. a node's image
        :param dest_path: local filesystem path to write the OVA to
        :return:
        :raises RuntimeError: Is thrown when no complete OVA could be downloaded after all attempts.
        """
        last_error: Exception | None = None
        for attempt in range(1, _OVA_DOWNLOAD_MAX_ATTEMPTS + 1):
            response = requests.get(
                f"{Settings.API.ESXI_TEMPLATE_SERVER_URL}/api/download",
                params={"name": template_name},
                stream=True,
                timeout=30,
            )
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=_OVA_DOWNLOAD_CHUNK_SIZE):
                    f.write(chunk)

            try:
                with tarfile.open(dest_path) as archive:
                    archive.getmembers()
            except tarfile.TarError as error:
                last_error = error
                logger.warning(
                    f"Downloaded OVA for '{template_name}' is incomplete or corrupt "
                    f"({error}); retrying ({attempt}/{_OVA_DOWNLOAD_MAX_ATTEMPTS})"
                )
                continue

            return

        logger.error(
            msg := f"Failed to download a complete OVA for '{template_name}' after "
            f"{_OVA_DOWNLOAD_MAX_ATTEMPTS} attempts: {last_error}"
        )
        raise RuntimeError(msg)

    @staticmethod
    def get_gns3_template_names() -> Set[str]:
        """
        Returns a set of available template names for GNS3
        :return: The set containing received template names.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        if Settings.API.LITERAL_API_VALUES:
            return Settings.API.LITERAL_GNS3_TEMPLATES
        data = APIHandler.get(f"{Settings.API.GNS3_TEMPLATE_SERVER_URL}/api/templates")
        return {template["name"] for template in data["templates"]}
