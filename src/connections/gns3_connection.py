from __future__ import annotations

import re
from typing import Any
from typing import TYPE_CHECKING

import requests

from ..settings import Verbosity, Settings

if TYPE_CHECKING:
    from src.graph import Graph
    from src.graph.blocks import GenericNode, Interface

from .api_handler import APIHandler
from src.graph.layout import compute_node_positions
from loguru import logger


# @TODO shortform and longform / better name dedection
class GNS3Connection(APIHandler):
    """
    Object which provides methods regarding the GNS3 API
    """

    def set_node_positions(self, graph: Graph) -> None:
        """
        Precomputes a force-directed canvas layout for every node in the
        graph, so create_node/_create_builtin_nodes can place each node
        sensibly relative to its neighbours instead of everything landing
        on the same hardcoded coordinate and piling up in the GNS3 Web UI.
        Call this once, right after construction, before creating any
        nodes.
        :param graph: the topology about to be deployed
        :return:
        """
        self._positions = {
            name: (int(x), int(y))
            for name, (x, y) in compute_node_positions(graph.nodes).items()
        }

    def _position_for(self, node_name: str) -> tuple[int, int]:
        """
        Returns the precomputed canvas position for a node, or a fallback
        if set_node_positions was never called (e.g. in tests) or the
        node wasn't part of the graph it was computed from.
        :param node_name: name of the node to position
        :return: (x, y) canvas coordinates
        """
        return getattr(self, "_positions", {}).get(node_name, (0, 0))

    def __init__(
        self, ip: str, port: int, project_name: str, incremental: bool = False
    ) -> None:
        """
        :param ip: GNS3 IP address
        :param port: GNS3 API port
        :param project_name: Name of the GNS3 project to work on
        :param incremental: if True, an existing project is reused as-is
            instead of being deleted and recreated, and create_node/
            connect_nodes skip anything that already exists by name/
            endpoint instead of creating a duplicate. Never removes a node
            dropped from the graph - use a full (non-incremental) deploy or
            destroy for that.
        :raises ValueError: Is thrown when the IPv4 address is not a public, private or loopback address.
        :raises TypeError: Is thrown when the parameters are of the wrong types.
        """

        super().__init__(ip, port)
        self.url = f"http://{ip}:{port}"
        self.incremental = incremental
        self._positions: dict[str, tuple[int, int]] = {}

        self.project_name = project_name
        self.project = self._init_project(project_name)

        self._existing_nodes_by_name: dict[str, dict[str, Any]] = {}
        self._existing_links: list[dict[str, Any]] = []
        if incremental and self.project is not None and not Settings.IS_DRY_RUN:
            self._existing_nodes_by_name = {
                node["name"]: node
                for node in GNS3Connection.list_project_nodes(
                    ip, port, self.project["project_id"]
                )
            }
            self._existing_links = GNS3Connection.list_project_links(
                ip, port, self.project["project_id"]
            )

    @staticmethod
    def get_version(ip: str, port: int) -> dict[str, Any]:
        """
        Returns the GNS3 server's own version/edition info. Purely
        read-only, side-effect-free reachability check - unlike
        constructing a GNS3Connection, this never touches a project.
        :param ip: GNS3 IP address
        :param port: GNS3 API port
        :return: dict with at least a 'version' key
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        return GNS3Connection.get(f"http://{ip}:{port}/v2/version")

    @staticmethod
    def list_all_projects(ip: str, port: int) -> list[dict[str, Any]]:
        """
        Lists every project on the given GNS3 server, open or not. Purely
        read-only - unlike constructing a GNS3Connection for one named
        project, this never creates or deletes anything.
        :param ip: GNS3 IP address
        :param port: GNS3 API port
        :return: list of project dicts, each with at least 'project_id' and 'name'
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        return GNS3Connection.get(f"http://{ip}:{port}/v2/projects")

    @staticmethod
    def list_project_nodes(ip: str, port: int, project_id: str) -> list[dict[str, Any]]:
        """
        Lists every node currently in the given project. Purely read-only.
        :param ip: GNS3 IP address
        :param port: GNS3 API port
        :param project_id: the project to list nodes for
        :return: list of node dicts, each with at least 'node_id', 'name', and 'status'
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        return GNS3Connection.get(f"http://{ip}:{port}/v2/projects/{project_id}/nodes")

    @staticmethod
    def list_project_links(ip: str, port: int, project_id: str) -> list[dict[str, Any]]:
        """
        Lists every link currently in the given project. Purely read-only.
        :param ip: GNS3 IP address
        :param port: GNS3 API port
        :param project_id: the project to list links for
        :return: list of link dicts, each with a 'nodes' list of
            {'node_id', 'adapter_number', 'port_number'} for both endpoints
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        return GNS3Connection.get(f"http://{ip}:{port}/v2/projects/{project_id}/links")

    def _init_project(self, name: str) -> dict[str, Any] | None:
        """
        Create a new GNS3 project. If project already exists, it is deleted
        first - unless ``self.incremental`` is set, in which case an
        existing project is reused as-is instead. Under
        ``Settings.IS_DRY_RUN``, neither deletes nor creates anything -
        returns the existing project's info read-only (or None if it
        doesn't exist yet), so dry-run stays genuinely side-effect-free.
        :param name: Name of the GNS3 project.
        :return: Returns the newly generated GNS3 project information. Returns ``None`` if the ``Settings.ONLY_ON_ESXI`` is ``True``.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the creation or deletion of an existing project fails. May also be thrown if it fails to collect project information.
        """
        if Settings.ONLY_ON_ESXI:
            return None
        try:
            projects = self.get(f"{self.url}/v2/projects")
        except requests.exceptions.HTTPError as exc:
            logger.error(msg := "Failed to collect GNS3 project information.")
            raise RuntimeError(msg) from exc

        project = next((p for p in projects if p["name"] == name), None)

        # ----------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            if project is None:
                Verbosity.volumatic_print(
                    Verbosity.NORMAL, f"Would create GNS3 project {name}"
                )
            else:
                Verbosity.volumatic_print(
                    Verbosity.NORMAL,
                    f"Would delete and recreate existing GNS3 project {name}",
                )
            return project
        # ----------------------------------------------------------------------------------------------------------

        if self.incremental:
            if project is None:
                return self._create_new_project(name)
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"GNS3 project {name} already exists, reusing it"
            )
            if project.get("status") != "opened":
                project = self.post(
                    f"{self.url}/v2/projects/{project['project_id']}/open"
                )
            return project

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
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the project does not exist on the GNS3 instance.
        """
        try:
            self.delete(f"{self.url}/v2/projects/{project_id}")
        except requests.exceptions.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 404:
                logger.error(
                    msg := f"GNS3 project {project_id} does not exist on {self.ip}"
                )
                raise RuntimeError(msg) from exc
            raise RuntimeError(
                f"Something went wrong with the deletion of a GNS3 project on {self.ip}"
            ) from exc

    def _create_new_project(self, name) -> dict[str, Any]:
        """
        Creates a new GNS3 project on the GNS3 instance.
        :param name: Name of the GNS3 project.
        :return: Returns the newly generated GNS3 project information.
        :raises RuntimeError: Is thrown when the project already exists on the GNS3 instance.
        May also be thrown if some other HTTPError occurs.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        """
        try:
            response = self.post(f"{self.url}/v2/projects", json={"name": name})
            return response
        except requests.exceptions.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 409:
                logger.error(msg := f"GNS3 project {name} already exists on {self.ip}")
                raise RuntimeError(msg) from exc
            raise RuntimeError(
                f"Something went wrong with the creation of the GNS3 project {name} on {self.ip}"
            ) from exc

    @staticmethod
    def _create_ports_mapping(node: GenericNode) -> list[dict[str, str]]:
        """
        Creates a ports mapping for GNS3 to specify the ports for the Cloud node.
        :param node: Node to create this mapping for.
        :return: Returns a list of dictionaries where each dictionary represents an interface on the Cloud.
        :raises RuntimeError: Is thrown when a vlan, which should exist, does not exist on the corresponding interface in the graph.
        """
        ports_mapping = []
        for port_number, interface in enumerate(node.interfaces.values()):
            vlan = interface.vlan
            if vlan is None:
                logger.error(
                    msg
                    := f"Something went wrong with the graph initialization. Needed VLAN does not exist on {node.name}.{interface.name}"
                )
                raise RuntimeError(msg)

            ports_mapping.append(
                {
                    "interface": f"{vlan.name}",
                    "name": interface.name,
                    "port_number": port_number,
                    "type": "ethernet",
                }
            )
        return ports_mapping

    def create_node(self, node: GenericNode) -> dict[str, Any] | None:
        """
        Creates a new GNS3 node on the GNS3 project.
        :param node: Node to be generated.
        :return: Returns the newly generated GNS3 node information. ``None`` is returned, if the ``Settings.IS_DRY_RUN`` or ``Settings.ONLY_ON_ESXI`` options are True.
        :raises ValueError: Is thrown when the image of the node does not exist on the GNS3 instance.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when it fails to collect GNS3 template information. May also be thrown when it fails to create the node.
        """
        from src.graph import Environment

        if Settings.ONLY_ON_ESXI:
            return None

        if self.incremental:
            existing = self._existing_nodes_by_name.get(node.name)
            if existing is not None:
                Verbosity.volumatic_print(
                    Verbosity.NORMAL,
                    f"Node {node.name} already exists on GNS3, reusing it (incremental)",
                )
                node.gns3_node_info = existing
                return existing

        if node.env == Environment.ON_ESXI:
            ports_mapping = self._create_ports_mapping(node)
            return self._create_builtin_nodes(node, "Cloud", ports_mapping)

        template = self._get_template(node.image)

        # --------------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"Would deploy {node.name} on GNS3. {node.image}"
            )
            return None
        Verbosity.volumatic_print(
            Verbosity.NORMAL, f"Deploys {node.name} on GNS3: {node.image}"
        )
        # --------------------------------------------------------------------------------------------------------------
        # If the template is a builtin (e.g.: VPC, Cloud or NAT) it requires special treatment
        if template["builtin"]:
            return self._create_builtin_nodes(node, template)

        x, y = self._position_for(node.name)
        payload = {"name": node.name, "x": x, "y": y}
        try:
            response = self.post(
                f"{self.url}/v2/projects/{self.project['project_id']}/templates/{template['template_id']}",
                json=payload,
            )
        except requests.exceptions.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 400:
                logger.error(msg := "Invalid GET request was made.")
                raise RuntimeError(msg) from exc
            raise RuntimeError(
                "Something went wrong with the creation of the node request."
            ) from exc

        node.gns3_node_info = response
        return response

    def _create_builtin_nodes(
        self,
        node: GenericNode,
        template: str | dict[str, Any],
        ports_mapping: list = None,
    ) -> dict[str, Any] | None:
        """
        Creates new GNS3 built-in nodes in the GNS3 project.
        :param node: Node to be generated.
        :param template: Name of the GNS3 template or already the GNS3 template.
        :param ports_mapping: Only used for nodes, whose environment is ``ON_ESXI`` and which are represented with the 'Cloud'-node,
        since this will alter the interface selection of the node. May not work with all node templates.
        :return: Returns the newly generated GNS3 node information. ``None`` is returned, when the IS_DRY_RUN option is set.
        :raises ValueError: Is thrown when the image of the node does not exist on the GNS3 instance.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when it fails to collect GNS3 template information. May also be thrown when it fails to create the node.
        """
        if isinstance(template, str):
            # ----------------------------------------------------------------------------------------------------------
            if Settings.IS_DRY_RUN:
                Verbosity.volumatic_print(
                    Verbosity.NORMAL, f"Would deploy {node.name} on GNS3. {template}"
                )
                return None
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"Deploys {node.name} on GNS3: {template}"
            )
            # ----------------------------------------------------------------------------------------------------------
            template = self._get_template(template)

        x, y = self._position_for(node.name)
        payload = {
            "name": node.name,
            "node_type": template["template_type"],
            "compute_id": "local",
            "x": x,
            "y": y,
        }

        if ports_mapping is not None:
            payload["properties"] = {"ports_mapping": ports_mapping}

        try:
            response = self.post(
                f"{self.url}/v2/projects/{self.project['project_id']}/nodes",
                json=payload,
            )
        except requests.exceptions.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 400:
                logger.error(msg := "Invalid GET request was made.")
                raise RuntimeError(msg) from exc
            raise RuntimeError(
                "Something went wrong with the creation of the node request."
            ) from exc

        node.gns3_node_info = response
        return response

    def _get_template(self, template_name: str) -> dict[str, Any]:
        """
        Gets the template information of a certain existing GNS3 template.
        :param template_name: Name of the GNS3 template to get the information.
        :return: Returns the information of the template.
        :raises ValueError: Is thrown when the template does not exist on the GNS3 instance.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when it fails to collect GNS3 template information.
        """
        try:
            response = self.get(f"{self.url}/v2/templates")
        except requests.exceptions.HTTPError as exc:
            logger.error(
                msg := f"Could not collect GNS3 template information on host {self.ip}"
            )
            raise RuntimeError(msg) from exc

        template = next((t for t in response if t["name"] == template_name), None)

        if template is None:
            raise ValueError(f"Template {template_name} does not exist on GNS3 VM")
        return template

    @staticmethod
    def _trailing_number(name: str) -> int | None:
        """
        Extracts the trailing digit run from a port name, e.g. 'gi0/2' ->
        2, 'Ethernet2' -> 2. Returns None if the name doesn't end in digits.
        """
        match = re.search(r"(\d+)$", name)
        return int(match.group(1)) if match else None

    @staticmethod
    def _get_adapter(gns3_node_info: dict[str, Any], intf: Interface) -> dict[str, Any]:
        """
        Looks for a GNS3 adapter matching the given interface. Tries, in
        order: exact name match (case-insensitive); if the node has
        exactly one port, that port regardless of name - single-port node
        types (e.g. VPCS's 'Ethernet0') often don't share the topology
        config's interface naming convention (e.g. 'gi0/0'), but there's
        no ambiguity when there's only one port; a port whose trailing
        number matches the requested name's trailing number, if exactly
        one candidate matches - different GNS3 templates have been
        observed to use different naming conventions entirely (e.g.
        'gi0/2' vs. plain 'Ethernet2'), but both still encode the same
        port index at the end.
        :param gns3_node_info: GNS3 node information.
        :param intf: Interface of the node.
        :return: Returns the GNS3 adapter information.
        :raises ValueError: Is thrown when no adapter can be associated with the given interface.
        This may happen because the names are not the same.
        """
        ports = gns3_node_info["ports"]
        for adapter in ports:
            if adapter["name"].lower() == intf.name.lower():
                return adapter

        if len(ports) == 1:
            logger.warning(
                f"Node '{gns3_node_info['name']}' has no port named "
                f"'{intf.name}', using its only port "
                f"'{ports[0].get('name')}' instead"
            )
            return ports[0]

        requested_number = GNS3Connection._trailing_number(intf.name)
        if requested_number is not None:
            matches = [
                adapter
                for adapter in ports
                if GNS3Connection._trailing_number(adapter.get("name", ""))
                == requested_number
            ]
            if len(matches) == 1:
                logger.warning(
                    f"Node '{gns3_node_info['name']}' has no port named "
                    f"'{intf.name}', using port '{matches[0].get('name')}' "
                    f"instead (matched by port number)"
                )
                return matches[0]

        raise ValueError(
            f"Interface {intf.name} on {intf.parent.name} cannot be associated to any adapter of the {gns3_node_info['name']} template."
        )

    def _link_exists(self, node_id_a: str, node_id_b: str) -> bool:
        """
        Checks whether a link already exists between the two given nodes,
        based on the links collected at construction time (incremental
        mode only).
        :param node_id_a: GNS3 node_id of one endpoint
        :param node_id_b: GNS3 node_id of the other endpoint
        :return: True if a link between exactly these two nodes already exists
        """
        wanted = {node_id_a, node_id_b}
        return any(
            {endpoint["node_id"] for endpoint in link["nodes"]} == wanted
            for link in self._existing_links
        )

    def connect_nodes(
        self, node_1: GenericNode, node_2: GenericNode
    ) -> dict[str, Any] | None:
        """
        Connects two GNS3 nodes from the same GNS3 project together.
        :param node_1: Node to connect to ``node_2``.
        :param node_2: Node to connect to ``node_1``.
        :return: Returns the newly generated GNS3 link information. `None`` is returned, if the ``Settings.IS_DRY_RUN`` or ``Settings.ONLY_ON_ESXI`` options are True.
        :raises ValueError: Is thrown when no adapter can be associated with the given interface.
        This may happen because the names are not the same.
        :raises RuntimeError: Is thrown when both nodes have no connection in the graph to each other.
        May also be thrown when one of the nodes does not exist in GNS3.
        """
        if Settings.ONLY_ON_ESXI:
            return None
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

        if self.incremental and self._link_exists(
            gns3_info_1["node_id"], gns3_info_2["node_id"]
        ):
            return None

        # --------------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(
                Verbosity.NORMAL,
                f"Would connect {node_1.name}[{intf_1.name}] to {node_2.name}[{intf_2.name}]",
            )
            return None
        Verbosity.volumatic_print(
            Verbosity.NORMAL,
            f"Connects {node_1.name}[{intf_1.name}] to {node_2.name}[{intf_2.name}]",
        )
        # --------------------------------------------------------------------------------------------------------------

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
        try:
            return self.post(
                f"{self.url}/v2/projects/{self.project['project_id']}/links",
                json=payload,
            )
        except requests.exceptions.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 400:
                logger.error(msg := "Invalid GET request was made.")
                raise RuntimeError(msg) from exc
            raise RuntimeError(
                f"Something went wrong while linking two nodes on {self.ip}"
            )

    def start_all_nodes(self) -> None:
        """
        Starts every node currently in this GNS3 project. GNS3 does not
        start a node automatically when it's created via the API - without
        this, deploy_graph would create and link every node but leave the
        whole topology powered off.
        :return: Returns ``None`` if the ``Settings.ONLY_ON_ESXI``/``Settings.IS_DRY_RUN`` options are True.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when it fails to collect the project's nodes, or when starting a node fails.
        """
        if Settings.ONLY_ON_ESXI:
            return
        # --------------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(Verbosity.NORMAL, "Would start all GNS3 nodes")
            return
        # --------------------------------------------------------------------------------------------------------------

        try:
            nodes = self.get(
                f"{self.url}/v2/projects/{self.project['project_id']}/nodes"
            )
        except requests.exceptions.HTTPError as exc:
            logger.error(msg := "Failed to collect GNS3 node information.")
            raise RuntimeError(msg) from exc

        for node in nodes:
            Verbosity.volumatic_print(
                Verbosity.NORMAL, f"Starts GNS3 node {node['name']}"
            )
            try:
                self.post(
                    f"{self.url}/v2/projects/{self.project['project_id']}/nodes/{node['node_id']}/start"
                )
            except requests.exceptions.HTTPError as exc:
                logger.error(msg := f"Failed to start GNS3 node {node['name']}")
                raise RuntimeError(msg) from exc
