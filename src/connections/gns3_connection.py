from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graph.blocks import GenericNode, Interface

from .api_handler import APIHandler

from src.logger_adapter import get_logger

logger = get_logger()


class GNS3Connection(APIHandler):
    """
    Object which provides methods regarding the GNS3 API
    """

    def __init__(self, ip: str, port: int, project_name: str) -> None:
        """
        :param ip: GNS3 IP address
        :param port: GNS3 API port
        :param project_name: Name of the GNS3 project to work on
        """
        super().__init__(ip, port)
        self.url = f"http://{ip}:{port}"

        self.project_name = project_name
        self.project = self._init_project(project_name)

    def _init_project(self, name: str) -> dict[str, Any]:
        """
        Create a new GNS3 project. If project already exists, it is deleted first.
        :param name: Name of the GNS3 project.
        :return: Returns the newly generated GNS3 project information.
        """
        projects = self.get(f"{self.url}/v2/projects").json()
        project = next((p for p in projects if p["name"] == name), None)

        if project is None:
            return self._create_new_project(name)
        else:
            self._remove_project(project["project_id"])
            return self._create_new_project(name)

    def _remove_project(self, project_id: str) -> None:
        """
        Removes the gns3 project from the GNS3 instance.
        :param project_id: Name of the GNS3 project.
        :return:
        """
        self.delete(f"{self.url}/v2/projects/{project_id}")

    def _create_new_project(self, name) -> dict[str, Any]:
        """
        Creates a new GNS3 project on the GNS3 instance.
        :param name: Name of the GNS3 project.
        :return: Returns the newly generated GNS3 project information.
        """
        response = self.post(f"{self.url}/v2/projects", json={"name": name}).json()
        return response

    @staticmethod
    def _create_ports_mapping(node: GenericNode) -> list[dict[str, str]]:
        """
        Creates a ports mapping for GNS3 to specify the ports for the Cloud node.
        :param node: Node to create this mapping for.
        :return: Returns a list of dictionaries where each dictionary represents an interface on the Cloud.
        :raises RuntimeError: Is thrown when a vlan, which should exist, does not exist on the corresponding interface.
        """
        ports_mapping = []
        for port_number, interface in enumerate(node.interfaces.values()):
            vlan = interface.vlan
            if vlan is None:
                raise logger.alert(
                    RuntimeError,
                    f"Something went wrong with the graph initialization. Needed VLAN does not exist on {node.name}.{interface.name}",
                )

            ports_mapping.append(
                {
                    "interface": f"{vlan.name}",
                    "name": interface.name,
                    "port_number": port_number,
                    "type": "ethernet",
                }
            )
        return ports_mapping

    def create_node(self, node: GenericNode) -> dict[str, Any]:
        """
        Creates a new GNS3 node on the GNS3 project.
        :param node: Node to be generated.
        :return: Returns the newly generated GNS3 node information.
        :raises ValueError: Is thrown when the image of the node does not exist on the GNS3 instance.
        """
        from src.graph import Environment

        if node.env == Environment.ON_ESXI:
            ports_mapping = self._create_ports_mapping(node)
            return self._create_builtin_nodes(node, "Cloud", ports_mapping)

        template = self._get_template(node.image)

        if template["builtin"]:
            return self._create_builtin_nodes(node, template)

        payload = {"name": node.name, "x": 100, "y": 100}
        response = self.post(
            f"{self.url}/v2/projects/{self.project['project_id']}/templates/{template['template_id']}",
            json=payload,
        ).json()

        node.gns3_node_info = response
        return response

    def _create_builtin_nodes(
        self,
        node: GenericNode,
        template: str | dict[str, Any],
        ports_mapping: list = None,
    ) -> dict[str, Any]:
        """
        Creates new GNS3 built-in nodes in the GNS3 project.
        :param node: Node to be generated.
        :param template: Name of the GNS3 template or already the GNS3 template.
        :param ports_mapping: Only used for nodes, whose environment is ``ON_ESXI`` and which are represented with the 'Cloud'-node,
        since this will alter the interface selection of the node. May not work with all node templates.
        :return: Returns the newly generated GNS3 node information.
        :raises ValueError: Is thrown when the image of the node does not exist on the GNS3 instance.
        """
        if isinstance(template, str):
            template = self._get_template(template)

        payload = {
            "name": node.name,
            "node_type": template["template_type"],
            "compute_id": "local",
            "x": 100,
            "y": 100,
        }

        if ports_mapping is not None:
            payload["properties"] = {"ports_mapping": ports_mapping}

        response = self.post(
            f"{self.url}/v2/projects/{self.project['project_id']}/nodes", json=payload
        ).json()

        node.gns3_node_info = response
        return response

    def _get_template(self, template_name: str) -> dict[str, Any]:
        """
        Gets the template information of a certain existing GNS3 template.
        :param template_name: Name of the GNS3 template to get the information.
        :return: Returns the information of the template.
        :raises ValueError: Is thrown when the template does not exist on the GNS3 instance.
        """
        response = self.get(f"{self.url}/v2/templates").json()
        template = next((t for t in response if t["name"] == template_name), None)

        if template is None:
            raise ValueError(f"Template {template_name} does not exist on GNS3 VM")
        return template

    @staticmethod
    def _get_adapter(gns3_node_info: dict[str, Any], intf: Interface) -> dict[str, Any]:
        """
        Looks for a gns3 adapter with the same name as given interface.
        :param gns3_node_info: GNS3 node information.
        :param intf: Interface of the node.
        :return: Returns the GNS3 adapter information.
        :raises ValueError: Is thrown when no adapter can be associated with the given interface.
        This may happen because the names are not the same.
        """
        for adapter in gns3_node_info["ports"]:
            # @TODO shortform and longform name dedection
            if adapter["name"].lower() == intf.name.lower():
                return adapter

        raise ValueError(
            f"Interface {intf.name} on {intf.parent.name} cannot be associated to any adapter of the {gns3_node_info['name']} template."
        )

    def connect_nodes(self, node_1: GenericNode, node_2: GenericNode) -> dict[str, Any]:
        """
        Connects two GNS3 nodes from the same GNS3 project together.
        :param node_1: Node to connect to ``node_2``.
        :param node_2: Node to connect to ``node_1``.
        :return: Returns the newly generated GNS3 link information.
        :raises ValueError: Is thrown when no adapter can be associated with the given interface.
        This may happen because the names are not the same.
        :raises RuntimeError: Is thrown when both nodes have no connection in the graph to each other.
        May also be thrown when one of the nodes does not exist in GNS3.
        """
        intf_1 = node_1.get_interface(node_2)
        intf_2 = node_2.get_interface(node_1)

        if intf_1 is None or intf_2 is None:
            raise RuntimeError(
                f"Node {node_1.name} has no internal connection to {node_2.name}"
            )

        gns3_info_1 = node_1.gns3_node_info
        gns3_info_2 = node_2.gns3_node_info

        if gns3_info_1 is None:
            raise RuntimeError(f"Node {node_1.name} does not exist on GNS3.")
        if gns3_info_2 is None:
            raise RuntimeError(f"Node {node_2.name} does not exist on GNS3.")

        adapter_1 = self._get_adapter(gns3_info_1, intf_1)
        adapter_2 = self._get_adapter(gns3_info_2, intf_2)

        payload = {
            "nodes": [
                {
                    "adapter_number": adapter_1["adapter_number"],
                    "node_id": node_1.gns3_node_info["node_id"],
                    "port_number": adapter_1["port_number"],
                },
                {
                    "adapter_number": adapter_2["adapter_number"],
                    "node_id": node_2.gns3_node_info["node_id"],
                    "port_number": adapter_2["port_number"],
                },
            ]
        }

        return self.post(
            f"{self.url}/v2/projects/{self.project['project_id']}/links", json=payload
        ).json()
