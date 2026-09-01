"""
Provides a class to make the provisioning of the GNS3 and ESXi VMs easier and setting certain
settings accordingly to the built topology.
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import re

from src.connections.esxi_connection import ESXiConnection
from src.connections.ssh_connection import SSHConnection
from src.connections.gns3_connection import GNS3Connection
from src.settings import Settings
from src.graph import Environment, Graph
from src.vm_orchestrator.gns3_vm_interface_setup import GNS3VMInterfaceSetup
from loguru import logger


# @TODO ExceptionHandling
# @TODO Complete and recursive Exception Documentation.
# @TODO upgrade Logging
class VMOrchestrator:
    """
    Object which controls the process of the VMs provisioning.
    """

    def __init__(
        self,
        esxi_host: str,
        esxi_port: int,
        esxi_username: str,
        esxi_password: str | None,
        gns3_vm_name: str,
    ) -> None:
        """
        :param esxi_host: IPv4 address of the ESXi host.
        :param esxi_port: Port number of the ESXi host, where the API requests are expected.
        :param esxi_username: username of the ESXi host.
        :param esxi_password: corresponding password for user.
        :param gns3_vm_name: Name of the GNS3 VM on the ESXi host.
        :raises RuntimeError: Is thrown when the GNS3 VM is not found on the ESXi host.
        :raises ValueError: Is thrown when invalid credentials are provided or the IPv4 address is not a public, private or loopback address.
        :raises TimeoutError: Is thrown when timeout occurs.
        :raises ConnectionError: Is thrown when the connection buildup fails.
        :raises TypeError: Is thrown when the parameters are of the wrong types.
        """
        if (
            not isinstance(esxi_host, str)
            or not isinstance(esxi_port, int)
            or not isinstance(esxi_username, str)
            or not (isinstance(esxi_password, str) or esxi_password is None)
        ):
            raise TypeError

        self.esxi_connection = ESXiConnection(
            esxi_host, esxi_port, esxi_username, esxi_password
        )

        gns3_vm_ip = self.esxi_connection.get_vm_ip_address(gns3_vm_name)
        if gns3_vm_ip is None:
            logger.error(
                msg
                := f"No VM found on ESXi Host: {self.esxi_connection.ip} with the name: {gns3_vm_name}"
            )
            raise RuntimeError(msg)
        self.gns3_vm_ip = gns3_vm_ip

    def deploy_graph(
        self,
        graph: Graph,
        gns3_username: str,
        gns3_password: str | None = None,
        incremental: bool = False,
    ) -> None:
        """
        Deploys the graph on the ESXi host and GNS3 VM. The connection between the nodes runs solely between GNS3.
        This is established with multiple port groups with unique vlans on the vSwitch in ESXi.
        Starts every created GNS3 node once linking is complete - GNS3 does
        not start a node automatically when it's created via the API.
        :param graph: Graph to deploy
        :param gns3_username: Username for the GNS3 VM
        :param gns3_password: Password for the GNS3 VM. Set to  None if no password is set.
        :param incremental: if True, skips resetting the ESXi vSwitch,
            deleting unused VMs (see delete_unused_vms - also skipped in
            incremental mode, same reasoning), and reuses an existing GNS3
            project instead of deleting and recreating it - only ESXi
            VMs/GNS3 nodes/links that don't already exist by name/endpoint
            get created, everything already present is left running
            untouched. Never removes anything dropped from the graph - use
            a full (non-incremental) deploy or destroy for that. Note: the
            GNS3 VM's VLAN subinterfaces are
            still fully torn down and recreated even in incremental mode,
            since that script always does a full delete+recreate pass - this
            briefly interrupts traffic on already-running Cloud-node
            bridges, unlike the ESXi/GNS3-node-level skipping incremental
            otherwise provides.
        :return:

        :raises TimeoutError: Is thrown when it took too long to receive a response.
        :raises ConnectionError: Is thrown when something on the connection buildup fails.
        :raises ValueError: Is thrown when the IPv4 address is not a public, private or loopback address.
            Is also thrown when the credentials are not valid.
            May also be thrown when no virtual Switch was found.
            May also be thrown when the image of the node does not exist on the GNS3 instance.
            May also be thrown when no adapter can be associated with the given interface.
        :raises RuntimeError: Is thrown when it fails to collect GNS3 template information. May also be thrown when it fails to create the node.
            May also be thrown when an error occurs while trying to get subinterface information or when the execution of the script fails.
            May also be thrown when there are issues with removing the port group, like it does not exist, or it is currently in use.
            May also be thrown when a portgroup already exists on the ESXi host. May also be thrown when no host-system or network-system was found on the ESXi host.
        """
        self._configure_gns3_interfaces(graph, gns3_username, gns3_password)
        if not incremental:
            self.delete_unused_vms(graph)
            self.esxi_connection.reset_virtual_switch()
        self.esxi_connection.initialize_virtual_switch(graph)

        gns3_conn = GNS3Connection(
            self.gns3_vm_ip,
            Settings.GNS3.PORT,
            Settings.GNS3.PROJECT_NAME,
            incremental=incremental,
        )

        for node in graph.nodes.values():
            if node.env == Environment.ON_ESXI:
                self.esxi_connection.deploy_virtual_machine(
                    node=node,
                    datastore=Settings.ESXI.DATASTORE,
                    incremental=incremental,
                )
                gns3_conn.create_node(node)

            if node.env == Environment.ON_GNS3:
                gns3_conn.create_node(node)

            self._partially_link_gns3_nodes(gns3_conn, node)

        gns3_conn.start_all_nodes()

    def delete_unused_vms(self, graph: Graph) -> None:
        """
        Deletes ESXi VMs this tool previously created (identified via
        their 'topologybuilder-image:' annotation, set on every VM this
        tool imports) that are neither the GNS3 VM nor part of the given
        graph's current ESXi-hosted nodes - cleans up leftovers from an
        earlier deploy of a *different* topology, which
        delete_stale_esxi_resources doesn't reach since it only ever
        looks at the current graph's own node names. Runs before
        resetting the vSwitch so a stale VM's NIC can't block port-group
        removal. Never touches a VM without that annotation, so anything
        not created by this tool (or created by a version of it that
        didn't yet tag VMs) is always left alone. No-op if
        ``Settings.ESXI.DELETE_UNUSED_VMS`` is False.
        :param graph: the current topology - its ESXi-hosted node names
            (and any auto-renamed-duplicate of them) are never deleted
            even if a matching VM carries the annotation
        :return:
        """
        if not Settings.ESXI.DELETE_UNUSED_VMS:
            return

        current_names = {
            node.name
            for node in graph.nodes.values()
            if node.env == Environment.ON_ESXI
        }
        gns3_vm = self.esxi_connection.find_gns3_vm()
        gns3_vm_name = gns3_vm.name if gns3_vm is not None else None

        for vm in self.esxi_connection.get_all_vms():
            if vm.name == gns3_vm_name:
                continue
            annotation = vm.config.annotation or ""
            if not annotation.startswith("topologybuilder-image:"):
                continue
            base_name = re.sub(r"[ _]\(?\d+\)?$", "", vm.name)
            if base_name in current_names:
                continue
            self.esxi_connection.delete_vm(vm)

    def delete_stale_esxi_resources(self, graph: Graph) -> None:
        """
        Deletes VMs and port groups left over from an earlier deploy of the
        graph's ESXi-hosted nodes, so redeploying doesn't accumulate
        duplicate/renamed VMs or leave a port group behind under the same
        name but a stale VLAN ID from a previous topology layout.
        :param graph: Graph whose ESXi-hosted nodes' stale resources to delete
        :return:
        """
        for node in graph.nodes.values():
            if node.env != Environment.ON_ESXI:
                continue

            for vm in self.esxi_connection.find_vms_matching(node.name):
                self.esxi_connection.delete_vm(vm)

            for interface in node.interfaces.values():
                if interface.vlan is not None:
                    self.esxi_connection.delete_port_group(interface.vlan.name)

    def destroy_graph(self, graph: Graph, project_name: str) -> None:
        """
        Tears down a previously deployed topology: deletes its ESXi-hosted
        VMs/port groups, and its GNS3 project's nodes (GNS3Connection's own
        constructor already deletes and recreates an existing project by
        name, which is exactly what's needed here too).
        :param graph: Graph whose deployed resources to tear down
        :param project_name: name of the GNS3 project to clear
        :return:
        """
        self.delete_stale_esxi_resources(graph)
        GNS3Connection(self.gns3_vm_ip, Settings.GNS3.PORT, project_name)

    def verify_graph(self, graph: Graph, project_name: str) -> list[tuple[bool, str]]:
        """
        Runs a structural health check against real infrastructure. This is
        NOT a connectivity/ping test - this project never assigns an IP
        address to any node from its own config, so there is no address to
        ping for either side of an edge. Checks: the GNS3 VM's trunk NIC is
        wired to ``Settings.ESXI.TRUNK_PORT_GROUP``; every GNS3-hosted node
        is 'started'; every ESXi-hosted VM is powered on and reports an IP
        via VMware Tools; both sides of a direct ESXi-ESXi link agree on
        VLAN ID; an ESXi<->GNS3 bridge's Cloud node exists (named after the
        ESXi node, per create_node's own convention); and a GNS3-internal
        link actually exists between the two node IDs.
        :param graph: built topology to verify
        :param project_name: name of the GNS3 project to check
        :return: list of (passed, description) tuples, one per check
        """
        results: list[tuple[bool, str]] = []
        port_groups = {
            pg["name"]: pg["vlan_id"] for pg in self.esxi_connection.list_port_groups()
        }

        gns3_nodes_by_name: dict[str, dict] = {}
        gns3_links: list[dict] = []
        project = next(
            (
                p
                for p in GNS3Connection.list_all_projects(
                    self.gns3_vm_ip, Settings.GNS3.PORT
                )
                if p.get("name") == project_name
            ),
            None,
        )
        if project is None:
            results.append((False, f"GNS3 project '{project_name}': not found"))
        else:
            gns3_nodes_by_name = {
                node.get("name"): node
                for node in GNS3Connection.list_project_nodes(
                    self.gns3_vm_ip, Settings.GNS3.PORT, project["project_id"]
                )
            }
            gns3_links = GNS3Connection.list_project_links(
                self.gns3_vm_ip, Settings.GNS3.PORT, project["project_id"]
            )

        gns3_vm = self.esxi_connection.get_vm(Settings.ESXI.GNS3_VM_NAME)
        if gns3_vm is None:
            results.append(
                (
                    False,
                    f"Trunk NIC wiring: '{Settings.ESXI.GNS3_VM_NAME}' VM not found",
                )
            )
        else:
            network_names = self.esxi_connection.get_vm_network_names(gns3_vm)
            ok = Settings.ESXI.TRUNK_PORT_GROUP in network_names
            results.append(
                (
                    ok,
                    f"Trunk NIC wiring: connected to '{Settings.ESXI.TRUNK_PORT_GROUP}'"
                    if ok
                    else f"Trunk NIC wiring: no network adapter connected to "
                    f"'{Settings.ESXI.TRUNK_PORT_GROUP}' (connected to: {network_names})",
                )
            )

        for name, node in graph.nodes.items():
            if node.env == Environment.ON_GNS3:
                gns3_node = gns3_nodes_by_name.get(name)
                if gns3_node is None:
                    results.append((False, f"GNS3 node '{name}': not found in project"))
                elif gns3_node.get("status") == "started":
                    results.append((True, f"GNS3 node '{name}': started"))
                else:
                    results.append(
                        (
                            False,
                            f"GNS3 node '{name}': status is '{gns3_node.get('status')}'",
                        )
                    )
            elif node.env == Environment.ON_ESXI:
                vm = self.esxi_connection.get_vm(name)
                if vm is None:
                    results.append((False, f"ESXi VM '{name}': not found"))
                elif not self.esxi_connection.is_vm_powered_on(vm):
                    results.append((False, f"ESXi VM '{name}': not powered on"))
                else:
                    ip_address = self.esxi_connection.get_vm_ip_address(name)
                    if ip_address is None:
                        results.append(
                            (
                                False,
                                f"ESXi VM '{name}': powered on, but no IP reported yet",
                            )
                        )
                    else:
                        results.append(
                            (True, f"ESXi VM '{name}': powered on, IP {ip_address}")
                        )

        seen_edges = set()
        for node in graph.nodes.values():
            for if_name, interface in node.interfaces.items():
                neighbour = interface.neighbour
                if neighbour is None:
                    continue

                neighbour_interface = neighbour.get_interface(node)
                neighbour_if_name = (
                    neighbour_interface.name if neighbour_interface else "?"
                )
                edge_key = frozenset(
                    [(node.name, if_name), (neighbour.name, neighbour_if_name)]
                )
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                label = (
                    f"{node.name}:{if_name} <-> {neighbour.name}:{neighbour_if_name}"
                )
                esxi_1 = node.env == Environment.ON_ESXI
                esxi_2 = neighbour.env == Environment.ON_ESXI

                if esxi_1 and esxi_2:
                    # A direct ESXi-to-ESXi link's two interfaces share the
                    # exact same VirtualLan object (see Graph._assign_vlans)
                    # - there's no bridging device to translate between two
                    # different VLANs, so both vNICs sit on the one shared
                    # port group by construction. Nothing to compare between
                    # "both sides" here, just confirm that shared port group
                    # actually exists on the live ESXi host.
                    vlan_name = interface.vlan.name if interface.vlan else None
                    vlan_id = port_groups.get(vlan_name) if vlan_name else None
                    if vlan_id is None:
                        results.append(
                            (False, f"{label}: port group '{vlan_name}' missing")
                        )
                    else:
                        results.append(
                            (
                                True,
                                f"{label}: VLAN {vlan_id} on shared port group '{vlan_name}'",
                            )
                        )
                elif esxi_1 or esxi_2:
                    esxi_node = node if esxi_1 else neighbour
                    if esxi_node.name not in gns3_nodes_by_name:
                        results.append(
                            (
                                False,
                                f"{label}: Cloud node for '{esxi_node.name}' not found",
                            )
                        )
                    else:
                        results.append(
                            (
                                True,
                                f"{label}: bridged via Cloud node '{esxi_node.name}'",
                            )
                        )
                else:
                    node_gns3 = gns3_nodes_by_name.get(node.name)
                    neighbour_gns3 = gns3_nodes_by_name.get(neighbour.name)
                    if node_gns3 is None or neighbour_gns3 is None:
                        results.append(
                            (False, f"{label}: one or both GNS3 nodes not found")
                        )
                        continue
                    ids = {node_gns3.get("node_id"), neighbour_gns3.get("node_id")}
                    linked = any(
                        {endpoint["node_id"] for endpoint in link["nodes"]} == ids
                        for link in gns3_links
                    )
                    results.append(
                        (
                            linked,
                            f"{label}: {'linked' if linked else 'no matching GNS3 link found'}",
                        )
                    )

        return results

    @staticmethod
    def _partially_link_gns3_nodes(gns3_connection: GNS3Connection, node) -> None:
        """
        Links only those nodes to this node who already exist on GNS3.
        :param gns3_connection: GNS3 API connection
        :param node: Node to connect to the other existing nodes.
        :return:
        :raises ValueError: Is thrown when no adapter can be associated with the given interface. This may happen because the names are not the same.
        :raises RuntimeError: Is thrown when both nodes have no connection in the graph to each other. May also be thrown when one of the nodes does not exist in GNS3.
        """
        for interface in node.interfaces:
            neighbour = node.get_neighbour(interface)
            if neighbour is None or neighbour.gns3_node_info is None:
                continue
            gns3_connection.connect_nodes(node, neighbour)

    def _configure_gns3_interfaces(
        self, graph: Graph, gns3_username: str, gns3_password: str | None
    ) -> None:
        """
        Configures the interfaces of the GNS3 VM to fit the graph. This is done to have an interface for each VLAN on the vSwitch.
        :param graph: Create the interfaces based on given graph.
        :param gns3_username: Username to connect to the GNS3 VM via ssh.
        :param gns3_password: Password to connect to the GNS3 VM via ssh.
        :return:
        :raises ValueError: Is thrown when the IPv4 address is not a public, private or loopback address. Is also thrown when the credentials are not valid.
        :raises TimeoutError: Is thrown when the connection buildup takes too long.
        :raises ConnectionError: Is thrown when the connection fails.
        :raises RuntimeError: Is thrown when an error occurs while trying to get subinterface information or when the execution of the script fails.
        """
        if Settings.ONLY_ON_ESXI:
            return

        port = 22

        gns3_connection = SSHConnection(
            self.gns3_vm_ip, port, gns3_username, gns3_password
        )
        gns3_interface_setup = GNS3VMInterfaceSetup(
            gns3_connection, Settings.GNS3.PARENT_INTERFACE
        )

        gns3_interface_setup.initialize_commands(graph)
        gns3_interface_setup.execute_script()
