import json

import requests
from loguru import logger

from src.settings import Settings

from .generic_connection import GenericConnection


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
    def get(
        url: str, parsing_method: str = "json", timeout: int = 5, **kwargs
    ) -> dict | None:
        """
        General method to make an API GET request
        :param parsing_method: Method of parsing the response.
        :param url: url to the API endpoint
        :param timeout: seconds to wait for a response before raising
            TimeoutError. Defaults to 5 - pass a larger value for a call
            expected to legitimately take longer.
        :param kwargs: Keyword arguments for the get request.
        :return: The parsed response from the GET request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the response is not parseable to JSON.
        """
        try:
            response = requests.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return APIHandler.parse_response(response, parsing_method)
        except requests.Timeout:
            logger.error(msg := f"GET request timed out to: {url}")
            raise TimeoutError(msg)
        except requests.HTTPError as err:
            logger.error(msg := f"GET request failed: {url}. Exception: {err}")
            raise

    @staticmethod
    def post(
        url: str, parsing_method: str = "json", timeout: int = 30, **kwargs
    ) -> dict | None:
        """
        General method to make an API POST request
        :param url: url to the API endpoint
        :param parsing_method: Method of parsing the response.
        :param timeout: seconds to wait for a response before raising
            TimeoutError. Defaults to 30 - pass a larger value for a call
            expected to legitimately take longer (e.g. GNS3 node start,
            which blocks until the node has booted).
        :param kwargs: Keyword arguments for the post request.
        :return: The parsed response from the POST request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the response is not parseable to JSON.
        """
        try:
            response = requests.post(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return APIHandler.parse_response(response, parsing_method)
        except requests.Timeout:
            logger.error(msg := f"POST request timed out to: {url}")
            raise TimeoutError(msg)
        except requests.HTTPError as err:
            logger.error(msg := f"POST request failed: {url}. Exception: {err}")
            raise

    @staticmethod
    def put(
        url: str, parsing_method: str = "json", timeout: int = 30, **kwargs
    ) -> dict | None:
        """
        General method to make an API PUT request
        :param url: url to the API endpoint
        :param parsing_method: Method of parsing the response.
        :param timeout: seconds to wait for a response before raising TimeoutError.
        :param kwargs: Keyword arguments for the put request.
        :return: The parsed response from the PUT request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the response is not parseable to JSON.
        """
        try:
            response = requests.put(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return APIHandler.parse_response(response, parsing_method)
        except requests.Timeout:
            logger.error(msg := f"PUT request timed out to: {url}")
            raise TimeoutError(msg)
        except requests.HTTPError as err:
            logger.error(msg := f"PUT request failed: {url}. Exception: {err}")
            raise

    @staticmethod
    def delete(
        url: str, parsing_method: str = "json", timeout: int = 5, **kwargs
    ) -> dict | None:
        """
        General method to make an API DELETE request
        :param url: url to the API endpoint
        :param parsing_method: Method of parsing the response.
        :param timeout: seconds to wait for a response before raising
            TimeoutError. Defaults to 5 (a plain metadata delete is
            normally near-instant) - pass a larger value for a call
            expected to legitimately take longer (e.g. deleting a GNS3
            node, which has to stop its live process first).
        :param kwargs: Keyword arguments for the delete request.
        :return: The parsed response from the DELETE request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the response is not parseable to JSON.
        """
        try:
            response = requests.delete(url, timeout=timeout, **kwargs)
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
    def get_esxi_template_names() -> set[str]:
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
    def _esxi_templates() -> list[dict]:
        return APIHandler.get(f"{Settings.API.ESXI_TEMPLATE_SERVER_URL}/api/templates")[
            "templates"
        ]

    @staticmethod
    def _template_url(template: dict) -> str:
        from src.pull_importer import ova_url

        return ova_url(
            Settings.API.OVA_BASE_URL,
            template.get("_source_dir") or "",
            template["file"],
        )

    @staticmethod
    def find_esxi_template_url(image: str) -> str:
        """
        Resolves a node's ``image`` to the URL an ESXi host downloads its OVA from (``Settings.API.OVA_BASE_URL``,
        the template's source directory and its exact file name).
        :param image: image name to search for, e.g. a node's image
        :return: the matched template's OVA URL.
        :raises ValueError: Is thrown when no template matches ``image``.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        from src.graph.environment import normalize_template_name

        normalized = normalize_template_name(image)
        for template in APIHandler._esxi_templates():
            if normalize_template_name(template["name"]) == normalized:
                return APIHandler._template_url(template)

        logger.error(msg := f"No ESXi template found matching image '{image}'")
        raise ValueError(msg)

    @staticmethod
    def find_esxi_template_url_by_file(file_name: str) -> str:
        """
        Resolves an exact OVA file name of the template catalog (its ``file`` field) to the URL of that OVA.
        :param file_name: exact file name of a template.
        :return: the OVA URL.
        :raises ValueError: Is thrown when no template has that file name.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        for template in APIHandler._esxi_templates():
            if template["file"] == file_name:
                return APIHandler._template_url(template)
        logger.error(msg := f"No ESXi template with the file '{file_name}'")
        raise ValueError(msg)

    @staticmethod
    def get_gns3_template_names() -> set[str]:
        """
        Returns a set of available template names for GNS3
        :return: The set containing received template names.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        if Settings.API.LITERAL_API_VALUES:
            return Settings.API.LITERAL_GNS3_TEMPLATES
        data = APIHandler.get(f"{Settings.API.GNS3_TEMPLATE_SERVER_URL}/api/templates")
        return {template["name"] for template in data["templates"]}
