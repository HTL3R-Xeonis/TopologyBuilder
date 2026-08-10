"""
Client for the GNS3 v2 controller API. Builds a project's actual nodes and
links from a built topology graph, bridging ESXi-hosted nodes in via Cloud
nodes bound to the matching VLAN subinterface on the GNS3 VM (the same
subinterfaces src/gns3_vm_interface_setup.py sets up).
"""

__license__ = "GNU GPLv3"

import requests

from src.factories import Environment, GenericNode
from src.graph_visualizer import compute_node_positions
from src.logger_adapter import get_logger

logger = get_logger(__name__)

_CLOUD_PORT_NAME = "eth0"

# Fields on a template object that describe the template itself, not the
# device it configures (e.g. platform, qemu_path, ram, hda_disk_image, ...).
# Everything NOT in this set gets copied into a new node's 'properties', since
# GNS3 doesn't fully inherit them from template_id alone - omitting them (e.g.
# 'platform') leaves the node half-configured, such as building a QEMU binary
# path like 'qemu-system-None'.
_TEMPLATE_META_FIELDS = {
    "template_id",
    "template_type",
    "name",
    "category",
    "builtin",
    "default_name_format",
    "symbol",
    "compute_id",
    "usage",
}


class GNS3Client:
    """
    Talks to the GNS3 v2 controller API.
    """

    def __init__(self, base_url: str) -> None:
        """
        :param base_url: base URL of the GNS3 VM, e.g. http://10.20.20.231
        """
        self.base_url = base_url.rstrip("/")

    def _raise_for_status(self, response: requests.Response) -> None:
        """
        Like Response.raise_for_status, but includes the response body in the
        raised error - the GNS3 API returns a JSON 'message' field explaining
        exactly what was wrong with the request, which a bare status code loses.
        """
        if not response.ok:
            raise logger.alert(
                requests.HTTPError,
                f"{response.status_code} error for {response.url}: {response.text}",
            )

    def _get(self, path: str):
        response = requests.get(f"{self.base_url}{path}")
        self._raise_for_status(response)
        return response.json()

    def _post(self, path: str, json: dict | None = None):
        response = requests.post(f"{self.base_url}{path}", json=json)
        self._raise_for_status(response)
        return response.json() if response.content else {}

    def get_templates(self) -> list[dict]:
        """
        Lists the GNS3 templates available on this server.
        :return: list of template dicts, each with at least 'template_id' and 'name'
        """
        return self._get("/v2/templates")

    def find_template(self, image: str) -> dict:
        """
        Resolves a node's configured image to a GNS3 template by exact name match.
        :param image: the image name as used in the topology config file
        :return: the matching template dict, including 'template_id' and 'template_type'
        """
        for template in self.get_templates():
            if template.get("name") == image:
                return template
        raise logger.alert(ValueError, f"No GNS3 template found for image '{image}'")

    def get_or_create_project(self, name: str) -> dict:
        """
        Finds an existing project by name, or creates one if none exists.
        Ensures the returned project is open.
        :param name: project name
        :return: project dict, including 'project_id'
        """
        for project in self._get("/v2/projects"):
            if project.get("name") == name:
                logger.info(f"Reusing existing GNS3 project '{name}'")
                if project.get("status") != "opened":
                    project = self._post(f"/v2/projects/{project['project_id']}/open")
                return project

        logger.info(f"Creating GNS3 project '{name}'")
        return self._post("/v2/projects", json={"name": name})

    def create_node(
        self, project_id: str, template: dict, name: str, x: int, y: int
    ) -> dict:
        """
        Creates a node from a template at the given scene position.
        :param template: template dict from find_template/get_templates
        :return: the created node dict, including 'node_id' and 'ports'
        """
        # Some template types (e.g. VPCS) already nest their device-specific
        # settings under their own 'properties' key; others (e.g. QEMU) have
        # them flat at the template's top level. Use the former as-is; for
        # the latter, collect everything that isn't template metadata.
        if "properties" in template:
            properties = template["properties"]
        else:
            properties = {
                key: value
                for key, value in template.items()
                if key not in _TEMPLATE_META_FIELDS
            }
        node = self._post(
            f"/v2/projects/{project_id}/nodes",
            json={
                "name": name,
                "template_id": template["template_id"],
                "node_type": template["template_type"],
                "compute_id": template.get("compute_id") or "local",
                "x": x,
                "y": y,
                "properties": properties,
            },
        )
        logger.info(f"Created GNS3 node '{name}' ({node['node_id']})")
        return node

    def create_cloud_node(
        self, project_id: str, name: str, host_interface: str, x: int, y: int
    ) -> dict:
        """
        Creates a Cloud node bound to a specific interface on the GNS3 VM
        host (a VLAN subinterface created for bridging to an ESXi VM), so a
        topology link can reach outside GNS3's own simulated nodes.
        :param host_interface: name of the host-side interface to bind to,
            e.g. an Interface.esxi_vlan subinterface name
        :return: the created node dict, including 'node_id'
        """
        node = self._post(
            f"/v2/projects/{project_id}/nodes",
            json={
                "node_type": "cloud",
                "compute_id": "local",
                "name": name,
                "x": x,
                "y": y,
                "properties": {
                    "ports_mapping": [
                        {
                            "name": _CLOUD_PORT_NAME,
                            "interface": host_interface,
                            "port_number": 0,
                            "type": "ethernet",
                        }
                    ]
                },
            },
        )
        logger.info(f"Created GNS3 cloud node '{name}' bound to {host_interface}")
        return node

    @staticmethod
    def _find_port(node: dict, interface_name: str) -> dict:
        """
        Finds a node's port matching the given interface name, case-insensitively.
        """
        for port in node.get("ports", []):
            if port.get("name", "").lower() == interface_name.lower():
                return port
        available = [port.get("name") for port in node.get("ports", [])]
        raise logger.alert(
            ValueError,
            f"No port named '{interface_name}' on node '{node.get('name')}'. "
            f"Available ports: {available}",
        )

    def create_link(
        self,
        project_id: str,
        node_a: dict,
        interface_a: str,
        node_b: dict,
        interface_b: str,
    ) -> dict:
        """
        Links two nodes' ports together, resolving each side by interface name.
        """
        port_a = self._find_port(node_a, interface_a)
        port_b = self._find_port(node_b, interface_b)
        link = self._post(
            f"/v2/projects/{project_id}/links",
            json={
                "nodes": [
                    {
                        "node_id": node_a["node_id"],
                        "adapter_number": port_a["adapter_number"],
                        "port_number": port_a["port_number"],
                    },
                    {
                        "node_id": node_b["node_id"],
                        "adapter_number": port_b["adapter_number"],
                        "port_number": port_b["port_number"],
                    },
                ]
            },
        )
        logger.info(
            f"Linked {node_a['name']}:{interface_a} -- {node_b['name']}:{interface_b}"
        )
        return link

    def start_all_nodes(self, project_id: str) -> None:
        """
        Starts every node in the project.
        """
        self._post(f"/v2/projects/{project_id}/nodes/start")
        logger.info("Started all GNS3 nodes")


def deploy_topology(
    base_url: str, project_name: str, nodes: dict[str, GenericNode]
) -> None:
    """
    Builds the given topology inside a GNS3 project: creates a node for every
    GNS3-hosted device, a Cloud node bridging each link that touches an
    ESXi-hosted device (via the VLAN subinterface Phase 1 sets up), and a
    link for every edge. Then starts all nodes.

    Edges where both endpoints are ESXi-hosted need no GNS3-side wiring at
    all - once Phase 3 provisions those VMs onto the matching port group,
    they reach each other directly.
    :param base_url: base URL of the GNS3 VM, e.g. http://10.20.20.231
    :param project_name: name of the GNS3 project to create or reuse
    :param nodes: built topology of nodes, as returned by GraphBuilder.build()
    """
    client = GNS3Client(base_url)
    project = client.get_or_create_project(project_name)
    project_id = project["project_id"]

    positions = compute_node_positions(nodes)

    gns3_nodes: dict[str, dict] = {}
    for name, node in nodes.items():
        if node.env != Environment.ON_GNS3:
            continue
        template = client.find_template(node.image)
        x, y = positions[name]
        gns3_nodes[name] = client.create_node(
            project_id, template, name, int(x) - 1000, int(y) - 500
        )

    seen_edges = set()
    for node in nodes.values():
        for interface in node.interfaces.values():
            edge = interface.edge
            if edge is None or id(edge) in seen_edges:
                continue
            seen_edges.add(id(edge))

            node_1, if_1 = edge.incidence_1.node, edge.incidence_1.name
            node_2, if_2 = edge.incidence_2.node, edge.incidence_2.name
            gns3_1 = node_1.env == Environment.ON_GNS3
            gns3_2 = node_2.env == Environment.ON_GNS3

            if gns3_1 and gns3_2:
                client.create_link(
                    project_id,
                    gns3_nodes[node_1.name],
                    if_1,
                    gns3_nodes[node_2.name],
                    if_2,
                )
            elif gns3_1 or gns3_2:
                gns3_interface, esxi_interface = (
                    (edge.incidence_1, edge.incidence_2)
                    if gns3_1
                    else (edge.incidence_2, edge.incidence_1)
                )
                x, y = positions[gns3_interface.node.name]
                cloud_node = client.create_cloud_node(
                    project_id,
                    f"cloud-{esxi_interface.esxi_vlan}",
                    esxi_interface.esxi_vlan,
                    int(x) - 1000 + 100,
                    int(y) - 500 + 100,
                )
                client.create_link(
                    project_id,
                    gns3_nodes[gns3_interface.node.name],
                    gns3_interface.name,
                    cloud_node,
                    _CLOUD_PORT_NAME,
                )
            # else: both ESXi-hosted, no GNS3 involvement needed.

    client.start_all_nodes(project_id)
