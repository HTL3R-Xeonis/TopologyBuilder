"""
Client for the GNS3 v2 controller API. Builds a project's actual nodes and
links from a built topology graph, bridging ESXi-hosted nodes in via Cloud
nodes bound to the matching VLAN subinterface on the GNS3 VM (the same
subinterfaces src/gns3_vm_interface_setup.py sets up).
"""

__license__ = "GNU GPLv3"

import re
import time

import requests

from src.factories import Environment, GenericNode, normalize_template_name
from src.graph_visualizer import compute_node_positions
from src.logger_adapter import get_logger

logger = get_logger(__name__)

_CLOUD_PORT_NAME = "eth0"
_DEFAULT_TIMEOUT_SECONDS = 30
# Starting or deleting a QEMU-backed node can be much slower than the other,
# purely metadata-level API calls (create project, list nodes, create link,
# ...) - GNS3's own controller has been observed to block synchronously on
# its compute backend for both, up to its own internal 240s per-node
# timeout. This is comfortably above that, so we don't time out client-side
# before GNS3 itself gives up on a slow node.
_NODE_LIFECYCLE_TIMEOUT_SECONDS = 300

# Matches the error GNS3 raises when a node's console TCP port is already
# bound by another process - observed intermittently on node start, most
# likely an orphaned QEMU process from an earlier delete not yet finished
# releasing the port (see Hard-won knowledge #21 in HANDOFF.md - never
# actually confirmed live before now). Retried once below since the port
# often frees itself within a few seconds.
_CONSOLE_PORT_COLLISION_PATTERN = re.compile(
    r"already in use|errno 98", re.IGNORECASE
)
_CONSOLE_PORT_COLLISION_RETRY_BACKOFF_SECONDS = 5


def is_console_port_collision_error(error: Exception) -> bool:
    """
    True if the given exception's message matches the known console-port-
    collision signature GNS3 returns on a node-start failure. Exposed at
    module level (not just used internally by start_all_nodes) so
    vm_orchestrator.py can recognize the same failure and capture SSH
    diagnostics when the retry in start_all_nodes doesn't resolve it.
    :param error: the exception raised by a failed node-start request
    :return: True if it matches the console-port-collision signature
    """
    return bool(_CONSOLE_PORT_COLLISION_PATTERN.search(str(error)))


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

    def _get(self, path: str, timeout: int = _DEFAULT_TIMEOUT_SECONDS):
        response = requests.get(f"{self.base_url}{path}", timeout=timeout)
        self._raise_for_status(response)
        return response.json()

    def _post(
        self,
        path: str,
        json: dict | None = None,
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
    ):
        response = requests.post(f"{self.base_url}{path}", json=json, timeout=timeout)
        self._raise_for_status(response)
        return response.json() if response.content else {}

    def _delete(self, path: str, timeout: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        response = requests.delete(f"{self.base_url}{path}", timeout=timeout)
        self._raise_for_status(response)

    def delete_all_nodes(self, project_id: str) -> None:
        """
        Deletes every node currently in the project (and, as a consequence,
        every link between them), so redeploying against an already-existing
        project starts from a clean slate instead of piling duplicate nodes
        on top of a previous run. Deleting a still-running QEMU-backed node
        can be just as slow as starting one under host load (observed as a
        client-side ReadTimeout at the previous, shorter default timeout),
        so each delete gets a generous timeout, and a failure on one node
        doesn't stop the rest from being cleaned up - node creation below
        already tolerates a leftover name collision (see the warning
        create_node logs in that case), so this is a best-effort cleanup
        rather than something the whole deploy needs to hard-fail on.
        :param project_id: the project to clear
        :return:
        """
        nodes = self._get(f"/v2/projects/{project_id}/nodes")
        failed_names = []
        for node in nodes:
            try:
                self._delete(
                    f"/v2/projects/{project_id}/nodes/{node['node_id']}",
                    timeout=_NODE_LIFECYCLE_TIMEOUT_SECONDS,
                )
            except requests.exceptions.RequestException as error:
                failed_names.append(node.get("name", node["node_id"]))
                logger.error(
                    f"Failed to delete existing node '{node.get('name')}': {error}"
                )

        if failed_names:
            logger.warning(
                f"Failed to delete {len(failed_names)}/{len(nodes)} existing "
                f"node(s) before redeploying: {failed_names}. Continuing - "
                f"node creation may pick up a renamed duplicate if a name "
                f"collides."
            )
        elif nodes:
            logger.info(f"Deleted {len(nodes)} existing node(s) before redeploying")

    def get_templates(self) -> list[dict]:
        """
        Lists the GNS3 templates available on this server.
        :return: list of template dicts, each with at least 'template_id' and 'name'
        """
        return self._get("/v2/templates")

    def find_template(self, image: str) -> dict:
        """
        Resolves a node's configured image to a GNS3 template. Matching
        ignores case and whitespace differences (see normalize_template_name)
        - real GNS3 installs have been observed to have template names that
        differ from a config's image name by exactly that kind of noise.
        :param image: the image name as used in the topology config file
        :return: the matching template dict, including 'template_id' and 'template_type'
        """
        normalized_image = normalize_template_name(image)
        for template in self.get_templates():
            if normalize_template_name(template.get("name", "")) == normalized_image:
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
        # the latter, collect everything that isn't template metadata. Empty
        # strings mean "not configured" in GNS3's template convention, but
        # some node schemas reject an empty string outright for fields like
        # mac_address/bios_image - omit them so the server applies its own
        # default instead of sending a value it'll refuse.
        if "properties" in template:
            properties = template["properties"]
        else:
            properties = {
                key: value
                for key, value in template.items()
                if key not in _TEMPLATE_META_FIELDS and value != ""
            }
        body = {
            "name": name,
            "template_id": template["template_id"],
            "node_type": template["template_type"],
            "compute_id": template.get("compute_id") or "local",
            "x": x,
            "y": y,
            "properties": properties,
        }
        # 'symbol' (the node's icon) is a top-level node field, not a device
        # property, so it's deliberately excluded from 'properties' above -
        # but it must still be forwarded here, or the server falls back to
        # its own default icon for the node_type instead of the template's.
        if template.get("symbol"):
            body["symbol"] = template["symbol"]
        node = self._post(f"/v2/projects/{project_id}/nodes", json=body)
        if node.get("name") != name:
            logger.warning(
                f"Requested GNS3 node name '{name}' but server assigned "
                f"'{node.get('name')}' instead (likely a name collision with "
                f"an existing node from a previous deploy of this project)"
            )
        logger.info(f"Created GNS3 node '{node.get('name')}' ({node['node_id']})")
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
    def _trailing_number(name: str) -> int | None:
        """
        Extracts the trailing digit run from a port name, e.g. 'gi0/2' -> 2,
        'Ethernet2' -> 2. Returns None if the name doesn't end in digits.
        """
        match = re.search(r"(\d+)$", name)
        return int(match.group(1)) if match else None

    @staticmethod
    def _find_port(node: dict, interface_name: str) -> dict:
        """
        Finds a node's port matching the given interface name. Tries, in order:
        1. exact match, case-insensitively;
        2. if the node has exactly one port, that port regardless of name -
           single-port node types (e.g. VPCS's 'Ethernet0') often don't share
           the topology config's interface naming convention (e.g. 'gi0/0'),
           but there's no ambiguity when there's only one port;
        3. a port whose trailing number matches the requested name's trailing
           number, if exactly one candidate matches - different GNS3 installs
           have been observed to use different naming conventions entirely
           (e.g. this config's 'gi0/2' vs. a template using plain 'Ethernet2'),
           but both still encode the same port index at the end.
        """
        ports = node.get("ports", [])
        for port in ports:
            if port.get("name", "").lower() == interface_name.lower():
                return port

        if len(ports) == 1:
            logger.warning(
                f"Node '{node.get('name')}' has no port named '{interface_name}', "
                f"using its only port '{ports[0].get('name')}' instead"
            )
            return ports[0]

        requested_number = GNS3Client._trailing_number(interface_name)
        if requested_number is not None:
            matches = [
                port
                for port in ports
                if GNS3Client._trailing_number(port.get("name", "")) == requested_number
            ]
            if len(matches) == 1:
                logger.warning(
                    f"Node '{node.get('name')}' has no port named "
                    f"'{interface_name}', using port '{matches[0].get('name')}' "
                    f"instead (matched by port number)"
                )
                return matches[0]

        available = [port.get("name") for port in ports]
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
        Starts every node in the project one at a time, rather than GNS3's
        own batch 'start all' endpoint. That endpoint has been observed to
        fail the entire operation when a single node's start exceeds GNS3's
        own internal 240s per-node compute timeout - easily triggered by
        starting many QEMU-backed nodes (e.g. several Cisco IOSv routers)
        at once on a resource-constrained host. Starting sequentially
        naturally staggers the actual work instead of firing every node's
        start simultaneously, and on a failure reports exactly which
        node(s) failed instead of an opaque all-or-nothing batch error -
        nodes that did start successfully are left running.

        A node-start failure matching the known console-port-collision
        signature (see is_console_port_collision_error) gets one retry
        after a short backoff before being counted as failed, since it's
        often a transient orphaned-process condition that clears itself.
        """
        nodes = self._get(f"/v2/projects/{project_id}/nodes")
        failed_names = []
        for node in nodes:
            try:
                self._post(
                    f"/v2/projects/{project_id}/nodes/{node['node_id']}/start",
                    timeout=_NODE_LIFECYCLE_TIMEOUT_SECONDS,
                )
                continue
            except requests.exceptions.RequestException as error:
                if is_console_port_collision_error(error):
                    logger.warning(
                        f"Node '{node['name']}' hit a console port collision "
                        f"on start, retrying once after "
                        f"{_CONSOLE_PORT_COLLISION_RETRY_BACKOFF_SECONDS}s"
                    )
                    time.sleep(_CONSOLE_PORT_COLLISION_RETRY_BACKOFF_SECONDS)
                    try:
                        self._post(
                            f"/v2/projects/{project_id}/nodes/{node['node_id']}/start",
                            timeout=_NODE_LIFECYCLE_TIMEOUT_SECONDS,
                        )
                        continue
                    except requests.exceptions.RequestException as retry_error:
                        error = retry_error

                failed_names.append(node["name"])
                logger.error(f"Failed to start node '{node['name']}': {error}")

        if failed_names:
            raise logger.alert(
                RuntimeError,
                f"Failed to start {len(failed_names)}/{len(nodes)} node(s): "
                f"{failed_names}. The rest started successfully; check the "
                f"GNS3 Web UI, then rerun deploy if needed (redeploys are "
                f"idempotent).",
            )
        logger.info(f"Started all {len(nodes)} GNS3 node(s)")


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

    Any nodes already in the project (e.g. from a previous deploy) are
    deleted first, so redeploying the same topology converges to a clean,
    correct state instead of accumulating duplicates.
    :param base_url: base URL of the GNS3 VM, e.g. http://10.20.20.231
    :param project_name: name of the GNS3 project to create or reuse
    :param nodes: built topology of nodes, as returned by GraphBuilder.build()
    """
    client = GNS3Client(base_url)
    project = client.get_or_create_project(project_name)
    project_id = project["project_id"]
    client.delete_all_nodes(project_id)

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
