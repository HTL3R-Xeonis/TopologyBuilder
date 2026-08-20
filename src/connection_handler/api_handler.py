import requests


class APIHandler:
    """
    Provides various methods for API calls.
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
        :param json: Data to be sent in the POST request
        :return:
        """
        response = requests.post(url, **kwargs)
        if not response.ok:
            print("URL:", url)
            print("STATUS:", response.status_code)
            print("BODY:", response.text)
            print("REQUEST JSON:", kwargs.get("json"))

        response.raise_for_status()
        return response

    @staticmethod
    def delete(url: str) -> requests.Response:
        response = requests.delete(url)
        response.raise_for_status()
        return response
