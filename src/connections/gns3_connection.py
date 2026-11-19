from __future__ import annotations

from typing import TYPE_CHECKING, Any

import requests

from src.settings import Settings, Verbosity

if TYPE_CHECKING:
    from src.graph.blocks import GenericNode, Interface

from loguru import logger

from .api_handler import APIHandler


# @TODO shortform and longform / better name dedection
class GNS3Connection(APIHandler):
    """
    Object which provides methods regarding the GNS3 API
    """

    def __init__(self, ip: str, port: int, project_name: str) -> None:
        """
        :param ip: GNS3 IP address
        :param port: GNS3 API port
        :param project_name: Name of the GNS3 project to work on
        :raises ValueError: Is thrown when the IPv4 address is not a public, private or loopback address.
        :raises TypeError: Is thrown when the parameters are of the wrong types.
        """

        super().__init__(ip, port)
        self.url = f"http://{ip}:{port}"

        self.project_name = project_name
        self.project_gns3_info = self._init_project(project_name)

    def _init_project(self, name: str) -> dict[str, Any]:
        """
        Returns the existing GNS3 project or creates it if missing.
        :param name: Name of the GNS3 project.
        :return: Returns the newly generated GNS3 project information.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when the creation or deletion of an existing project fails. May also be thrown if it fails to collect project information.
        """

        try:
            projects = self.get(f"{self.url}/v2/projects")
        except requests.exceptions.HTTPError as exc:
            logger.error(msg := "Failed to collect GNS3 project information.")
            raise RuntimeError(msg) from exc

        project = next((p for p in projects if p["name"] == name), None)
        if project is None:
            return self._create_new_project(name)
        if project.get("status") == "closed":
            try:
                return self.post(f"{self.url}/v2/projects/{project['project_id']}/open", json={})
            except requests.exceptions.HTTPError as exc:
                raise RuntimeError(f"Failed to open GNS3 project {name}.") from exc
        return project

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
                logger.error(msg := f"GNS3 project {project_id} does not exist on {self.ip}")
                raise RuntimeError(msg) from exc
            raise RuntimeError(f"Something went wrong with the deletion of a GNS3 project on {self.ip}") from exc

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

    def get_project_url(self) -> str:
        """:return: URL for the connected GNS3 project."""
        return f"{self.url}/v2/projects/{self.project_gns3_info['project_id']}"

    @staticmethod
    def _create_ports_mapping(node: GenericNode, connected_only: bool = False) -> list[dict[str, Any]]:
        """
        Returns VLAN port mappings for an ESXi-backed Cloud.
        :param node: ESXi node represented by the Cloud.
        :param connected_only: Prefer linked ports, falling back to the first port.
        :return: VLAN mappings for the selected graph interfaces.
        :raises ValueError: If the node has no interfaces.
        :raises RuntimeError: If an interface has no VLAN.
        """
        if not node.interfaces:
            raise ValueError(f"{node.name}: an ESXi-backed Cloud requires an interface")
        ports = []
        connected = []
        for interface in node.interfaces.values():
            if interface.vlan is None:
                raise RuntimeError(f"{node.name}.{interface.name}: no VLAN assigned to Cloud interface")
            port = {
                "interface": interface.vlan.name,
                "name": interface.vlan.name,
                "port_number": len(ports),
                "type": "ethernet",
            }
            ports.append(port)
            if interface.neighbour is not None:
                connected.append(port)
        return (connected or ports[:1]) if connected_only else ports

    def create_node(self, node: GenericNode) -> dict[str, Any] | None:
        """
        Creates a new GNS3 node on the GNS3 project.
        :param node: Node to be generated.
        :return: Returns the newly generated GNS3 node information. ``None`` is returned, if the ``Settings.IS_DRY_RUN`` value is True.
        :raises ValueError: Is thrown when the image of the node does not exist on the GNS3 instance.
        :raises TimeoutError: Is thrown when it takes too long to receive a response.
        :raises RuntimeError: Is thrown when it fails to collect GNS3 template information. May also be thrown when it fails to create the node or provide the Cloud port.
        """
        from src.graph import Environment

        if node.env == Environment.ON_ESXI:
            initial_port = self._create_ports_mapping(node, connected_only=True)[0]
            return self._create_builtin_nodes(node, "Cloud", [{**initial_port, "port_number": 0}])

        template = self._get_template(node.image)

        # --------------------------------------------------------------------------------------------------------------
        if Settings.IS_DRY_RUN:
            Verbosity.volumatic_print(Verbosity.NORMAL, f"Would deploy {node.name} on GNS3: {node.image}")
            return None
        Verbosity.volumatic_print(Verbosity.NORMAL, f"Deploys {node.name} on GNS3: {node.image}")
        # --------------------------------------------------------------------------------------------------------------
        # If the template is a builtin (e.g.: VPC, Cloud or NAT) it requires special treatment
        if template["builtin"]:
            return self._create_builtin_nodes(node, template)

        payload = {"name": node.name, "x": 100, "y": 100}
        try:
            response = self.post(
                f"{self.url}/v2/projects/{self.project_gns3_info['project_id']}/templates/{template['template_id']}",
                json=payload,
            )
        except requests.exceptions.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 400:
                logger.error(msg := "Invalid GET request was made.")
                raise RuntimeError(msg) from exc
            raise RuntimeError("Something went wrong with the creation of the node request.") from exc

        node.node_gns3_info = response
        return response

    def _create_builtin_nodes(
        self,
        node: GenericNode,
        template: str | dict[str, Any],
        ports_mapping: list | None = None,
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
                Verbosity.volumatic_print(Verbosity.NORMAL, f"Would deploy {node.name} on GNS3: {template}")
                return None
            Verbosity.volumatic_print(Verbosity.NORMAL, f"Deploys {node.name} on GNS3: {template}")
            # ----------------------------------------------------------------------------------------------------------
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

        try:
            response = self.post(
                f"{self.url}/v2/projects/{self.project_gns3_info['project_id']}/nodes",
                json=payload,
            )
        except requests.exceptions.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 400:
                logger.error(msg := "Invalid GET request was made.")
                raise RuntimeError(msg) from exc
            raise RuntimeError("Something went wrong with the creation of the node request.") from exc

        node.node_gns3_info = response
        if ports_mapping is not None:
            return self.ensure_cloud_ports(node, ports_mapping)
        return response

    def update_node(self, node: GenericNode, properties: dict[str, Any]) -> dict[str, Any]:
        """
        Updates a GNS3 node and refreshes its port information.
        :param node: Existing graph node.
        :param properties: Desired node properties.
        :return: Updated GNS3 node information.
        :raises RuntimeError: If the node cannot be updated or retrieved.
        :raises requests.RequestException: If the GNS3 request fails.
        """
        if node.node_gns3_info is None:
            raise RuntimeError(f"GNS3 node {node.name} does not exist")
        url = f"{self.get_project_url()}/nodes/{node.node_gns3_info['node_id']}"
        response = requests.put(url, json=properties, timeout=30)
        response.raise_for_status()
        current = self.get(url)
        if not isinstance(current, dict):
            raise TypeError(f"Cannot read updated GNS3 node {node.name}")
        node.node_gns3_info = current
        return current

    @staticmethod
    def _missing_cloud_ports_mapping(
        current: dict[str, Any], required: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        """
        Returns an extended Cloud mapping only when required ports are missing.
        :param current: Existing GNS3 Cloud information.
        :param required: VLAN ports requested by the graph.
        :return: Updated mapping, or None if all ports are available.
        :raises RuntimeError: If existing ports cannot be preserved safely.
        """
        present = {port.get("name", "").casefold() for port in current.get("ports") or []}
        mapping = [dict(port) for port in (current.get("properties") or {}).get("ports_mapping") or []]
        mapped = {port.get("name", "").casefold(): port for port in mapping}
        if len(mapped) != len(mapping) or any(name not in mapped for name in present):
            raise RuntimeError(f"Cannot safely extend Cloud {current.get('name', '')}: unknown or duplicate ports")

        active_vlans = {port["interface"].casefold() for port in mapping if port["name"].casefold() in present}
        missing = [port for port in required if port["interface"].casefold() not in active_vlans]
        if not missing:
            return None

        next_port = max((port["port_number"] for port in mapping), default=-1) + 1
        for port in missing:
            name = port["name"].casefold()
            if name in mapped:
                if mapped[name]["interface"].casefold() != port["interface"].casefold():
                    raise RuntimeError(f"Cannot reuse Cloud port {port['name']}: VLAN interface differs")
                continue
            addition = {**port, "port_number": next_port}
            mapping.append(addition)
            mapped[name] = addition
            next_port += 1
        return mapping

    def ensure_cloud_ports(self, node: GenericNode, required: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """
        Adds missing graph ports to a Cloud without changing existing ports.
        :param node: ESXi-backed GNS3 Cloud node.
        :param required: Optional ports needed for the initial Cloud creation.
        :return: Current GNS3 Cloud information.
        :raises ValueError: If the graph has no interfaces.
        :raises RuntimeError: If a required port cannot be safely added.
        :raises requests.RequestException: If the GNS3 update fails.
        """
        current = node.node_gns3_info
        if current is None:
            raise RuntimeError(f"GNS3 Cloud {node.name} does not exist")
        expected = required if required is not None else self._create_ports_mapping(node)
        mapping = self._missing_cloud_ports_mapping(current, expected)
        if mapping is not None:
            properties = current.get("properties") or {}
            current = self.update_node(node, {"properties": {**properties, "ports_mapping": mapping}})
        if self._missing_cloud_ports_mapping(current, expected) is not None:
            raise RuntimeError(f"GNS3 Cloud {node.name} is missing required VLAN ports")
        return current

    def _get_template(self, template_name: str) -> Any:
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
            logger.error(msg := f"Could not collect GNS3 template information on host {self.ip}")
            raise RuntimeError(msg) from exc

        template = next((t for t in response if t["name"] == template_name), None)

        if template is None:
            raise ValueError(f"Template {template_name} does not exist on GNS3 VM")
        return template

    @staticmethod
    def _get_adapter(gns3_node_info: dict[str, Any], intf: Interface) -> dict[str, Any]:
        """
        Returns the GNS3 port assigned to a graph interface or its VLAN.
        :param gns3_node_info: GNS3 node information.
        :param intf: Graph interface to resolve.
        :return: Matching GNS3 adapter information.
        :raises ValueError: If no corresponding GNS3 adapter exists.
        """
        is_vlan_cloud = gns3_node_info.get("node_type") == "cloud" and intf.vlan is not None
        mappings = (
            {
                port["name"].casefold(): port.get("interface", "").casefold()
                for port in (gns3_node_info.get("properties") or {}).get("ports_mapping") or []
            }
            if is_vlan_cloud
            else {}
        )
        expected = intf.vlan.name.casefold() if is_vlan_cloud else intf.name.casefold()
        for adapter in gns3_node_info["ports"]:
            name = adapter["name"].casefold()
            if mappings.get(name, name) == expected:
                return adapter

        raise ValueError(
            f"Interface {intf.name} on {intf.parent.name} cannot be associated to any adapter of the {gns3_node_info['name']} template."
        )

    def connect_nodes(self, node_1: GenericNode, node_2: GenericNode) -> dict[str, Any] | None:
        """
        Connects two GNS3 nodes from the same GNS3 project together.
        :param node_1: Node to connect to ``node_2``.
        :param node_2: Node to connect to ``node_1``.
        :return: Returns the newly generated GNS3 link information. `None`` is returned, if the ``Settings.IS_DRY_RUN`` value is True.
        :raises ValueError: Is thrown when no adapter can be associated with the given interface.
        This may happen because the names are not the same.
        :raises RuntimeError: Is thrown when both nodes have no connection in the graph to each other.
        May also be thrown when one of the nodes does not exist in GNS3.
        """

        intf_1 = node_1.get_interface(node_2)
        intf_2 = node_2.get_interface(node_1)

        if intf_1 is None or intf_2 is None:
            raise RuntimeError(f"Node {node_1.name} has no internal connection to {node_2.name}")
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

        gns3_info_1 = node_1.node_gns3_info
        gns3_info_2 = node_2.node_gns3_info

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
                    "node_id": node_1.node_gns3_info["node_id"],
                    "port_number": adapter_1["port_number"],
                },
                {
                    "adapter_number": adapter_2["adapter_number"],
                    "node_id": node_2.node_gns3_info["node_id"],
                    "port_number": adapter_2["port_number"],
                },
            ]
        }
        try:
            return self.post(
                f"{self.url}/v2/projects/{self.project_gns3_info['project_id']}/links",
                json=payload,
            )
        except requests.exceptions.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 400:
                logger.error(msg := "Invalid GET request was made.")
                raise RuntimeError(msg) from exc
            raise RuntimeError(f"Something went wrong while linking two nodes on {self.ip}")
