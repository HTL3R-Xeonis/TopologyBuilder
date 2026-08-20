from typing import Any, Optional


from src.connection_handler.api_handler import APIHandler
from src.graph_builder.factories import GenericNode, Interface
from src.graph_builder.graph_builder import GraphBuilder
from src.logger_adapter import get_logger

logger = get_logger()


class GNS3Connection(APIHandler):
    def __init__(
        self, ip: str, port: int, project_name: str = "tb_gns3_project"
    ) -> None:
        super().__init__(ip, port)
        self.url = f"http://{ip}:{port}/v2"

        self.project_name = project_name
        self.project = self._init_project(project_name)
        print(self.project["project_id"])

    def _init_project(self, name: str) -> dict[str, Any]:
        projects = self.get(f"{self.url}/projects").json()
        if not isinstance(projects, list):
            print(projects)
            raise ValueError("API response is faulty")
        project = next((p for p in projects if p["name"] == name), None)

        if project is None:
            return self._create_new_project(name)
        else:
            self._remove_project(project["project_id"])
            return self._create_new_project(name)

    def _remove_project(self, project_id: str) -> None:
        self.delete(f"{self.url}/projects/{project_id}")

    def _create_new_project(self, name) -> dict[str, Any]:
        response = self.post(f"{self.url}/projects", json={"name": name}).json()
        if not isinstance(response, dict):
            raise ValueError("API response is faulty")
        return response

    def create_node(self, node: GenericNode) -> dict[str, Any]:
        template = self.get_template(node.image)

        if template is None:
            raise ValueError(f"Template {node.image} does not exist on GNS3 VM")

        if template["builtin"]:
            return self.create_builtin_nodes(node, template)

        payload = {"name": node.name, "x": 100, "y": 100}
        print(node)
        print(template)
        response = self.post(
            f"{self.url}/projects/{self.project['project_id']}/templates/{template['template_id']}",
            json=payload,
        ).json()

        node.gns3_node_info = response
        return response

    def create_builtin_nodes(
        self,
        node: GenericNode,
        template: str | dict[str, Any],
        ports_mapping: list = None,
    ) -> dict[str, Any]:
        print(template)
        if isinstance(template, str):
            template_data = self.get_template(template)

            if template_data is None:
                raise ValueError(f"Template {template_data} does not exist on GNS3 VM")
            template = template_data

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
            f"{self.url}/projects/{self.project['project_id']}/nodes", json=payload
        ).json()

        node.gns3_node_info = response
        return response

    def get_template(self, template_name: str) -> Optional[dict[str, Any]]:
        response = self.get(f"{self.url}/templates").json()
        template = next((t for t in response if t["name"] == template_name), None)
        return template

    def _get_adapter_number(
        self, gns3_node_info: dict[str, Any], intf: Interface
    ) -> Optional[dict[str, Any]]:
        for adapter in gns3_node_info["ports"]:
            if adapter["name"].lower() == intf.name.lower():
                return adapter
        return None

    def connect_nodes(self, node_1: GenericNode, node_2: GenericNode) -> dict[str, Any]:
        intf_1 = node_1.get_interface_to_neighbour(node_2)
        intf_2 = node_2.get_interface_to_neighbour(node_1)

        if intf_1 is None or intf_2 is None:
            raise RuntimeError(
                f"Node {node_1.name} has no internal connection to {node_2.name}"
            )

        adapter_1 = self._get_adapter_number(node_1.gns3_node_info, intf_1)
        adapter_2 = self._get_adapter_number(node_2.gns3_node_info, intf_2)

        if adapter_1 is None:
            raise ValueError(
                f"Interface {intf_1} on {node_1} cannot be associated to any template adapter"
            )
        if adapter_2 is None:
            raise ValueError(
                f"Interface {intf_2} on {node_2} cannot be associated to any template adapter"
            )

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
            f"{self.url}/projects/{self.project['project_id']}/links", json=payload
        ).json()


if __name__ == "__main__":
    host = GNS3Connection("10.20.20.221", 80)

    nodes = [
        {
            "image": "Cisco IOSv 15.6(1)T",
            "role": "ROUTER",
            "names": ["POP-ISP1-1", "ISP1-BB1"],
        }
    ]
    edges = [["POP-ISP1-1", "gi0/1", "ISP1-BB1", "gi0/0"]]
    g = GraphBuilder(nodes, edges)
    nodes = g.build()

    print(host.project)
    print(host.create_node(nodes["ISP1-BB1"]))
    print(host.create_node(nodes["POP-ISP1-1"]))
    print(host.connect_nodes(nodes["ISP1-BB1"], nodes["POP-ISP1-1"]))
