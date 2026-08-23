import requests


class APIHandler:
    """
    Base class for API methods.
    """

    def __init__(self, ip: str, port: int):
        self.ip = ip
        self.port = port

    @staticmethod
    def get(url: str) -> requests.Response:
        """
        General method to make an API GET request
        :param url: API url
        :return:
        """
        response = requests.get(url)
        response.raise_for_status()
        return response

    @staticmethod
    def post(url: str, **kwargs) -> requests.Response:
        """
        General method to make an API GET request
        :param url: API url
        :param kwargs: Keyword arguments for the post request.
        :return:
        """
        response = requests.post(url, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def delete(url: str) -> requests.Response:
        response = requests.delete(url)
        response.raise_for_status()
        return response

    @staticmethod
    def get_esxi_template_names():
        """
        Returns a set of available template names for ESXi
        :return:
        """
        json = APIHandler.get("http://10.20.20.171:8000/api/templates").json()
        return {template["name"] for template in json["templates"]}

    @staticmethod
    def get_ova(template_name):
        json = APIHandler.get(
            f"http://10.20.20.171:8000/api/search?name={template_name}"
        ).json()
        return next((r for r in json["results"]))["template"]["file"]

    @staticmethod
    def get_gns3_template_names():
        """
        Returns a set of available template names for GNS3
        :return:
        """
        json = APIHandler.get("http://10.20.20.171:8001/api/templates").json()
        return {template["name"] for template in json["templates"]}
