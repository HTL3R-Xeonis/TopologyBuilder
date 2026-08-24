import requests
from typing import Set


class APIHandler:
    """
    Base class for API methods.
    """

    def __init__(self, ip: str, port: int):
        """
        :param ip: IP address of the API server
        :param port: Port of the API server
        """
        self.ip = ip
        self.port = port

    @staticmethod
    def get(url: str, **kwargs) -> requests.Response:
        """
        General method to make an API GET request
        :param url: url to the API endpoint
        :param kwargs: Keyword arguments for the get request.
        :return: The response from the GET request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        """
        response = requests.get(url, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def post(url: str, **kwargs) -> requests.Response:
        """
        General method to make an API POST request
        :param url: url to the API endpoint
        :param kwargs: Keyword arguments for the post request.
        :return: The response from the POST request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        """
        response = requests.post(url, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def delete(url: str, **kwargs) -> requests.Response:
        """
        General method to make an API DELETE request
        :param url: url to the API endpoint
        :param kwargs: Keyword arguments for the delete request.
        :return: The response from the DELETE request.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        """
        response = requests.delete(url, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def get_esxi_template_names() -> Set[str]:
        """
        Returns a set of available template names for ESXi.
        :return: The set containing received template names.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        """
        json = APIHandler.get("http://10.20.20.171:8000/api/templates").json()
        return {template["name"] for template in json["templates"]}

    @staticmethod
    def get_ova(template_name) -> str:
        """
        Returns the ova file name of the first matching template.
        :param template_name: Name of the template.
        :return: Returns the ova file name of the template.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        """
        json = APIHandler.get(
            f"http://10.20.20.171:8000/api/search?name={template_name}"
        ).json()
        return next((r for r in json["results"]))["template"]["file"]

    @staticmethod
    def get_gns3_template_names() -> Set[str]:
        """
        Returns a set of available template names for GNS3
        :return: The set containing received template names.
        :raises HTTPError: Is thrown when something went wrong with the API call.
        """
        json = APIHandler.get("http://10.20.20.171:8001/api/templates").json()
        return {template["name"] for template in json["templates"]}
