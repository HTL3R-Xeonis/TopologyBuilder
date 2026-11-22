import json
from time import perf_counter

import requests
from loguru import logger

from src.settings import Settings
from src.settings.logging_config import safe_endpoint

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
    def _request(method: str, url: str, parsing_method: str = "json", **kwargs) -> dict | None:
        """
        Executes and records an HTTP request without logging its payload or credentials.
        :param method: HTTP method (GET, POST or DELETE).
        :param url: Target API URL.
        :param parsing_method: Expected response format.
        :param kwargs: Arguments forwarded to Requests.
        :return: Parsed API response.
        :raises TimeoutError: If the request times out.
        :raises requests.RequestException: If transport or HTTP status fails.
        :raises ValueError: If the API response cannot be parsed.
        """
        endpoint = safe_endpoint(url)
        request = {"GET": requests.get, "POST": requests.post, "DELETE": requests.delete}[method]
        started = perf_counter()
        try:
            response = request(url, **kwargs)
            response.raise_for_status()
        except requests.Timeout as exc:
            logger.error("HTTP {} timed out: {} ({:.2f}s)", method, endpoint, perf_counter() - started)
            raise TimeoutError(f"{method} request timed out: {endpoint}") from exc
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.error(
                "HTTP {} failed: endpoint={}, status={}, elapsed={:.2f}s, exception={}",
                method,
                endpoint,
                status,
                perf_counter() - started,
                type(exc).__name__,
            )
            raise
        result = APIHandler.parse_response(response, parsing_method)
        return result

    @staticmethod
    def get(url: str, parsing_method: str = "json", **kwargs) -> dict | None:
        """
        Retrieves and parses an HTTP API resource.
        :param url: Target API URL.
        :param parsing_method: Expected response format.
        :param kwargs: Arguments forwarded to Requests.
        :return: Parsed API response.
        :raises TimeoutError: If the request times out.
        :raises requests.RequestException: If the HTTP request fails.
        :raises ValueError: If the response is invalid.
        """
        kwargs.setdefault("timeout", 5)
        return APIHandler._request("GET", url, parsing_method, **kwargs)

    @staticmethod
    def post(url: str, parsing_method: str = "json", **kwargs) -> dict | None:
        """
        Submits and parses an HTTP API request.
        :param url: Target API URL.
        :param parsing_method: Expected response format.
        :param kwargs: Arguments forwarded to Requests; POST timeouts are caller-controlled.
        :return: Parsed API response.
        :raises TimeoutError: If the request times out.
        :raises requests.RequestException: If the HTTP request fails.
        :raises ValueError: If the response is invalid.
        """
        return APIHandler._request("POST", url, parsing_method, **kwargs)

    @staticmethod
    def delete(url: str, parsing_method: str = "json", **kwargs) -> dict | None:
        """
        Deletes and parses an HTTP API resource.
        :param url: Target API URL.
        :param parsing_method: Expected response format.
        :param kwargs: Arguments forwarded to Requests.
        :return: Parsed API response, if available.
        :raises TimeoutError: If the request times out.
        :raises requests.RequestException: If the HTTP request fails.
        :raises ValueError: If the response is invalid.
        """
        kwargs.setdefault("timeout", 5)
        return APIHandler._request("DELETE", url, parsing_method, **kwargs)

    @staticmethod
    def parse_response(response: requests.Response, parsing_method: str = "json") -> None | dict:
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
        except (json.decoder.JSONDecodeError, requests.exceptions.JSONDecodeError) as exc:
            logger.error(
                "Invalid API JSON: endpoint={}, status={}, exception={}",
                safe_endpoint(response.url),
                response.status_code,
                type(exc).__name__,
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
    def get_ova(template_name: str) -> str:
        """
        Returns the ova file name of the first matching template.
        :param template_name: Name of the template.
        :return: Returns the ova file name of the template.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        data = APIHandler.get(f"{Settings.API.ESXI_TEMPLATE_SERVER_URL}/api/search?name={template_name}")
        template = next(r for r in data["results"])["template"]
        return f"{template['_source_dir']}/{template['file']}"

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
