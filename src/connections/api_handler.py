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
    def find_esxi_template_file(image: str) -> str:
        """
        Resolves a node's ``image`` to the exact OVA filename on the
        ESXi Template-API's NFS share, for use with the OVA-deploy API's
        ``ova_filename`` field (which does a plain filename lookup on its
        own mounted template directory, not a fuzzy name match).
        :param image: image name to search for, e.g. a node's image
        :return: the matched template's exact OVA filename.
        :raises ValueError: Is thrown when no template matches ``image``.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        from src.graph.environment import normalize_template_name

        data = APIHandler.get(f"{Settings.API.ESXI_TEMPLATE_SERVER_URL}/api/templates")
        normalized = normalize_template_name(image)
        for template in data["templates"]:
            if normalize_template_name(template["name"]) == normalized:
                return template["file"]

        logger.error(msg := f"No ESXi template found matching image '{image}'")
        raise ValueError(msg)

    @staticmethod
    def deploy_ova(
        ip: str,
        port: int,
        vm_name: str,
        ova_filename: str,
        datastore: str,
        network: dict[str, str],
    ) -> None:
        """
        Deploys an OVA straight from the TopologyBuilderServices API's own
        NFS mount to ESXi, entirely server-side - no local download/upload
        hop on this project's side.
        :param ip: IP address of the ESXi host.
        :param port: Port of the ESXi host.
        :param vm_name: Name to give the imported VM.
        :param ova_filename: Exact OVA filename on the service's NFS mount.
        :param datastore: Name of the datastore to import onto.
        :param network: Mapping of the OVA's interface names to ESXi port group names.
        :return:
        :raises RuntimeError: Is thrown when the API call fails.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        try:
            response = requests.post(
                f"{Settings.API.OVA_DEPLOY_URL}/deploy/ova",
                json={
                    "ip": ip,
                    "port": port,
                    "vm_name": vm_name,
                    "ova_filename": ova_filename,
                    "datastore": datastore,
                    "network": network,
                },
                timeout=Settings.API.OVA_DEPLOY_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.Timeout:
            logger.error(msg := f"OVA deploy request timed out for VM '{vm_name}'")
            raise TimeoutError(msg)
        except requests.exceptions.RequestException as error:
            logger.error(
                msg := f"OVA deploy request failed for VM '{vm_name}': {error}. "
                f"Response: {getattr(error.response, 'text', '')}"
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
