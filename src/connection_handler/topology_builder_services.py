from src.connection_handler.api_handler import APIHandler
from src.settings import Settings


class TopologyBuilderServices(APIHandler):
    @staticmethod
    def get_esxi_template_names():
        """
        Returns a set of available template names for ESXi
        :return:
        """
        if Settings.Testing.GithubWorkflow.LITERAL_API_VALUES:
            return Settings.Testing.GithubWorkflow.LITERAL_ESXI_TEMPLATES
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
        if Settings.Testing.GithubWorkflow.LITERAL_API_VALUES:
            return Settings.Testing.GithubWorkflow.LITERAL_GNS3_TEMPLATES
        json = APIHandler.get("http://10.20.20.171:8001/api/templates").json()
        return {template["name"] for template in json["templates"]}
