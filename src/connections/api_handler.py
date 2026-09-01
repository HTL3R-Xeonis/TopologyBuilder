import json
from typing import Set

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
    def get_ova(template_name: str) -> str:
        """
        Returns the ova file name of the first matching template.
        :param template_name: Name of the template.
        :return: Returns the ova file name of the template.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        data = APIHandler.get(
            f"{Settings.API.ESXI_TEMPLATE_SERVER_URL}/api/search?name={template_name}"
        )
        return next((r for r in data["results"]))["template"]["file"]

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
