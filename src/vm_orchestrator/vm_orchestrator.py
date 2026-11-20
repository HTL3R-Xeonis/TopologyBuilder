"""
Provides a class to make the provisioning of the GNS3 and ESXi VMs easier and setting certain
settings accordingly to the built topology.
"""

__autor__ = "Leon Eiböck"
__date__ = "28/07/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

from src.connections.api_handler import APIHandler
from src.connections.esxi_connection import ESXiConnection
from src.connections.gns3_connection import (
    GNS3Connection,
    is_console_port_collision_error,
)
from src.connections.ssh_connection import SSHConnection
from src.graph import Environment, Graph
from src.pull_importer import check_ova_readable
from src.settings import Settings
from src.settings.settings import clamp_ova_deploy_parallel
from src.vm_orchestrator.gns3_vm_interface_setup import GNS3VMInterfaceSetup


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
        self.gns3_vm_name = gns3_vm_name

    def deploy_graph(
        self,
        graph: Graph,
        gns3_username: str,
        gns3_password: str | None = None,
        incremental: bool = False,
        on_progress: Callable[[str], None] | None = None,
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
            deleting unused VMs (see delete_unused_vms) and stale
            same-topology VMs (see delete_stale_esxi_resources - both also
            skipped in incremental mode, same reasoning), and reuses an
            existing GNS3 project instead of deleting and recreating it -
            only ESXi
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
        :param on_progress: Optional callback that gets one plain-text line per finished ESXi VM while the VMs are imported in
            parallel ("ESXi VM PC1 deployed (2 of 5, 41 s)"); the same lines are always logged.
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
        logger.info(
            f"Deploying {len(graph.nodes)} node(s) to project "
            f"'{Settings.GNS3.PROJECT_NAME}' (incremental={incremental})"
        )
        if not incremental:
            self.check_templates_readable(graph)
        else:
            # The ids come from the position in the file, which an added link shifts: keep the ids of the port
            # groups that exist, before anything (subinterfaces, port groups, Cloud ports) is built from them.
            conflicts = self._adopt_esxi_vlan_ids(graph)
            if conflicts:
                raise RuntimeError(
                    "Not deploying: "
                    + self._describe_vlan_conflicts(conflicts)
                    + " Run 'verify --fix' to re-tag them, or do a full deploy."
                )
        self._configure_gns3_interfaces(graph, gns3_username, gns3_password)
        self.esxi_connection.ensure_virtual_switch_exists()
        if not incremental:
            self.delete_unused_vms(graph)
            self.delete_stale_esxi_resources(graph)
            self.esxi_connection.reset_virtual_switch()
        self.esxi_connection.initialize_virtual_switch(graph)

        gns3_conn = GNS3Connection(
            self.gns3_vm_ip,
            Settings.GNS3.PORT,
            Settings.GNS3.PROJECT_NAME,
            incremental=incremental,
        )
        gns3_conn.set_node_positions(graph)

        datastore_name = Settings.ESXI.DATASTORE
        if datastore_name is None and any(
            node.env == Environment.ON_ESXI for node in graph.nodes.values()
        ):
            biggest = self.esxi_connection.find_biggest_datastore()
            datastore_name = biggest.name
            free_gb = biggest.summary.freeSpace / (1024**3)
            logger.info(
                f"No datastore configured, auto-selected '{datastore_name}' "
                f"({free_gb:.1f} GB free)"
            )

        # The OVA imports are the slow part and independent of each other: with Settings.API.OVA_DEPLOY_PARALLEL > 1 they run
        # side by side first; the GNS3 side below stays strictly sequential, so node creation and linking keep their order.
        deployed_in_parallel = self._deploy_esxi_nodes_in_parallel(
            graph, datastore_name, incremental, on_progress
        )

        for node in graph.nodes.values():
            if node.env == Environment.ON_ESXI:
                if not deployed_in_parallel:
                    self.esxi_connection.deploy_virtual_machine(
                        node=node,
                        datastore=datastore_name,
                        incremental=incremental,
                    )
                gns3_conn.create_node(node)

            if node.env == Environment.ON_GNS3:
                gns3_conn.create_node(node)

            self._partially_link_gns3_nodes(gns3_conn, node)

        try:
            gns3_conn.start_all_nodes()
        except RuntimeError as error:
            if is_console_port_collision_error(error):
                self._log_console_port_collision_diagnostics(
                    gns3_username, gns3_password
                )
            raise

        logger.info(f"Deployment complete: project '{Settings.GNS3.PROJECT_NAME}'")

    def _adopt_esxi_vlan_ids(self, graph: Graph) -> list[tuple[str, int, int]]:
        """
        Gives the graph's VLANs the ids their port groups already have on the ESXi vSwitch (see
        ``Graph.adopt_vlan_ids``), so a link added to an existing topology does not shift the ids of the others.
        Nothing changes without a vSwitch or port groups yet (first deploy), with ``Settings.ONLY_ON_GNS3`` or
        when ESXi cannot be read.
        :param graph: graph whose VLAN ids are adjusted in place
        :return: (port group name, id on ESXi, id assigned) of every port group that could not keep its id
        """
        if Settings.ONLY_ON_GNS3:
            return []
        try:
            existing = {
                pg["name"]: pg["vlan_id"]
                for pg in self.esxi_connection.list_port_groups()
            }
        except ValueError:  # no vSwitch yet: nothing to keep stable
            return []
        if not existing:
            return []
        return graph.adopt_vlan_ids(existing)

    @staticmethod
    def _describe_vlan_conflicts(conflicts: list[tuple[str, int, int]]) -> str:
        return "; ".join(
            f"port group '{name}' has VLAN id {actual} on ESXi, which another port group of this topology "
            f"already uses (it would need {wanted})"
            for name, actual, wanted in conflicts
        )

    def _deploy_esxi_nodes_in_parallel(
        self,
        graph: Graph,
        datastore_name: str | None,
        incremental: bool,
        on_progress: Callable[[str], None] | None,
    ) -> bool:
        """
        Imports the graph's ESXi-hosted nodes side by side - at most Settings.API.OVA_DEPLOY_PARALLEL at a time (the same cap
        is enforced per host inside ESXiConnection.deploy_virtual_machine, so other callers count too). Every started import
        runs to its end; one failing VM does not abort the others, and the VMs that did deploy stay on the host (an
        incremental re-run picks them up). Nothing here creates GNS3 nodes: the caller does that afterwards, in graph order.
        :param graph: the topology being deployed
        :param datastore_name: datastore for the VMs
        :param incremental: True skips VMs that already exist
        :param on_progress: optional callback for one text line per finished VM
        :return: True when the parallel phase handled the ESXi nodes, False when the caller has to deploy them one by one
            (a single ESXi node, OVA_DEPLOY_PARALLEL=1, a dry run, or a GNS3-only run).
        :raises RuntimeError: Is thrown, after every import has ended, when at least one VM failed; the text names the VMs
            that were deployed and each failed one with its error.
        """
        nodes = [n for n in graph.nodes.values() if n.env == Environment.ON_ESXI]
        workers = min(
            clamp_ova_deploy_parallel(Settings.API.OVA_DEPLOY_PARALLEL), len(nodes)
        )
        if workers <= 1 or Settings.IS_DRY_RUN or Settings.ONLY_ON_GNS3:
            return False

        logger.info(
            f"Importing {len(nodes)} ESXi VM(s), up to {workers} at the same time"
        )
        finished = 0
        counter_lock = threading.Lock()
        outcomes: dict[str, str | None] = {}

        def announce(line: str) -> None:
            logger.info(line)
            if on_progress is not None:
                try:
                    on_progress(line)
                except Exception:  # noqa: BLE001  # a broken progress sink must never fail a deploy
                    logger.exception("on_progress callback failed")

        def deploy_one(node) -> None:
            nonlocal finished
            started = time.monotonic()
            error: str | None = None
            try:
                self.esxi_connection.deploy_virtual_machine(
                    node=node, datastore=datastore_name, incremental=incremental
                )
            except Exception as exc:  # noqa: BLE001  # collected and reported below, per VM
                error = f"{type(exc).__name__}: {exc}"
            with counter_lock:
                finished += 1
                outcomes[node.name] = error
                position = f"{finished} of {len(nodes)}"
            seconds = time.monotonic() - started
            if error is None:
                announce(f"ESXi VM {node.name} deployed ({position}, {seconds:.0f} s)")
            else:
                announce(
                    f"ESXi VM {node.name} FAILED ({position}, {seconds:.0f} s): {error}"
                )

        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="esxi-deploy"
        ) as pool:
            for future in [pool.submit(deploy_one, node) for node in nodes]:
                future.result()

        failed = {name: err for name, err in outcomes.items() if err is not None}
        if failed:
            deployed = sorted(name for name, err in outcomes.items() if err is None)
            msg = (
                f"{len(deployed)} of {len(nodes)} ESXi VM(s) deployed"
                f" ({', '.join(deployed) or 'none'}); failed: "
                + "; ".join(f"{name}: {err}" for name, err in sorted(failed.items()))
                + ". The deployed VMs stay on the host - fix the failure and deploy again incrementally."
            )
            logger.error(msg)
            raise RuntimeError(msg)
        return True

    @staticmethod
    def check_templates_readable(graph: Graph) -> None:
        """
        Makes sure every OVA the graph's ESXi-hosted nodes need can be read, BEFORE a full deploy removes anything: a
        template file the share can not deliver would otherwise fail the deploy after the old VMs are already deleted.
        Each image is checked once.
        :param graph: the topology about to be deployed
        :return:
        :raises ValueError: Is thrown when an image has no matching template.
        :raises RuntimeError: Is thrown when a template file can not be read; nothing has been changed at that point.
        """
        checked: set[str] = set()
        for node in graph.nodes.values():
            if node.env != Environment.ON_ESXI or node.image in checked:
                continue
            checked.add(node.image)
            url = APIHandler.find_esxi_template_url(node.image)
            try:
                check_ova_readable(url)
            except RuntimeError as error:
                msg = (
                    f"Not deploying: the template of '{node.name}' ({node.image}) "
                    f"is not usable - {error}. Nothing was changed."
                )
                logger.error(msg)
                raise RuntimeError(msg) from error

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
        name but a stale VLAN ID from a previous topology layout. Port
        group names are deduped across all ESXi nodes, not just within
        one - a direct ESXi-to-ESXi link's two interfaces share the exact
        same VirtualLan object (see Graph._assign_vlans), so without this
        the shared port group would get a redundant second delete call.
        :param graph: Graph whose ESXi-hosted nodes' stale resources to delete
        :return:
        """
        deleted_port_group_names: set[str] = set()
        for node in graph.nodes.values():
            if node.env != Environment.ON_ESXI:
                continue

            for vm in self.esxi_connection.find_vms_matching(node.name):
                self.esxi_connection.delete_vm(vm)

            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None or vlan.name in deleted_port_group_names:
                    continue
                deleted_port_group_names.add(vlan.name)
                self.esxi_connection.delete_port_group(vlan.name)

    def destroy_graph(self, graph: Graph, project_name: str) -> None:
        """
        Tears down a previously deployed topology: deletes its ESXi-hosted
        VMs/port groups, and deletes its GNS3 project entirely - the
        project itself no longer exists afterwards, not just its nodes.
        :param graph: Graph whose deployed resources to tear down
        :param project_name: name of the GNS3 project to delete
        :return:
        """
        logger.info(f"Destroying project '{project_name}'")
        self.delete_stale_esxi_resources(graph)
        GNS3Connection.delete_project(self.gns3_vm_ip, Settings.GNS3.PORT, project_name)
        logger.info(f"Destroy complete: project '{project_name}'")

    def check_prerequisites(self) -> list[tuple[bool, str]]:
        """
        Read-only preflight check against real infrastructure, independent
        of any topology file: whether the vSwitch/trunk port group exist
        (or would be auto-created by a real deploy), which datastore a
        deploy would use and its free space, whether the GNS3 VM is
        reachable, and whether the Template-APIs are reachable. Never
        mutates anything - auto-create only happens as part of a real
        ``deploy_graph`` call.
        :return: list of (passed, description) tuples, one per check
        """
        results: list[tuple[bool, str]] = []

        vswitch_name = Settings.ESXI.VIRTUAL_SWITCH
        if self.esxi_connection.find_virtual_switch() is not None:
            results.append((True, f"vSwitch '{vswitch_name}': exists"))
        else:
            results.append(
                (True, f"vSwitch '{vswitch_name}': missing, would be auto-created")
            )

        trunk_port_group_name = Settings.ESXI.TRUNK_PORT_GROUP
        trunk_port_group = self.esxi_connection.find_port_group(trunk_port_group_name)
        if trunk_port_group is None:
            results.append(
                (
                    True,
                    (
                        f"Trunk port group '{trunk_port_group_name}': missing, "
                        f"would be auto-created"
                    ),
                )
            )
        elif self.esxi_connection.bridging_security_policy_ok(trunk_port_group):
            results.append(
                (
                    True,
                    (
                        f"Trunk port group '{trunk_port_group_name}': exists, "
                        f"security policy OK"
                    ),
                )
            )
        else:
            results.append(
                (
                    False,
                    (
                        f"Trunk port group '{trunk_port_group_name}': exists, but "
                        f"security policy is not yet correct (fixed automatically "
                        f"by the next deploy)"
                    ),
                )
            )

        try:
            if Settings.ESXI.DATASTORE is not None:
                datastore = self.esxi_connection.find_datastore(Settings.ESXI.DATASTORE)
                free_gb = datastore.summary.freeSpace / (1024**3)
                results.append(
                    (
                        True,
                        (
                            f"Datastore '{Settings.ESXI.DATASTORE}': exists, "
                            f"{free_gb:.1f} GB free"
                        ),
                    )
                )
            else:
                datastore = self.esxi_connection.find_biggest_datastore()
                free_gb = datastore.summary.freeSpace / (1024**3)
                results.append(
                    (
                        True,
                        (
                            f"Datastore: none configured, would auto-pick "
                            f"'{datastore.name}' ({free_gb:.1f} GB free)"
                        ),
                    )
                )
        except ValueError as error:
            results.append((False, f"Datastore: {error}"))

        gns3_ip = self.esxi_connection.get_vm_ip_address(self.gns3_vm_name)
        if gns3_ip is None:
            results.append(
                (
                    False,
                    f"GNS3 VM '{self.gns3_vm_name}': not found or no IP reported yet",
                )
            )
        else:
            try:
                version = GNS3Connection.get_version(gns3_ip, Settings.GNS3.PORT)
                results.append(
                    (
                        True,
                        (
                            f"GNS3 VM '{self.gns3_vm_name}' at {gns3_ip}: reachable "
                            f"(GNS3 {version.get('version', '?')})"
                        ),
                    )
                )
            except Exception as error:  # noqa: BLE001 - best effort or a check: the failure becomes a result or a warning, never a crash
                results.append(
                    (
                        False,
                        (
                            f"GNS3 VM '{self.gns3_vm_name}' at {gns3_ip}: not "
                            f"reachable ({error})"
                        ),
                    )
                )

        if Settings.API.LITERAL_API_VALUES:
            results.append((True, "Template-APIs: skipped (literal API values in use)"))
        else:
            try:
                esxi_templates = APIHandler.get_esxi_template_names()
                gns3_templates = APIHandler.get_gns3_template_names()
                results.append(
                    (
                        True,
                        (
                            f"Template-APIs: reachable ({len(esxi_templates)} ESXi, "
                            f"{len(gns3_templates)} GNS3 template(s))"
                        ),
                    )
                )
            except Exception as error:  # noqa: BLE001 - best effort or a check: the failure becomes a result or a warning, never a crash
                results.append((False, f"Template-APIs: not reachable ({error})"))

        return results

    def _verify_trunk_security_policy(self) -> tuple[bool, str] | None:
        """
        Checks that the trunk port group accepts promiscuous mode, MAC address
        changes and forged transmits. With ESXi's default policy (reject) all
        traffic bridged between a GNS3 node and an ESXi VM is dropped silently,
        although every other check passes.
        :return: (passed, description), or None if there is no ESXi side to check (``Settings.ONLY_ON_GNS3``)
        """
        if Settings.ONLY_ON_GNS3:
            return None
        name = Settings.ESXI.TRUNK_PORT_GROUP
        try:
            port_group = self.esxi_connection.find_port_group(name)
            if port_group is None:
                return False, f"Trunk port group '{name}': does not exist"
            if self.esxi_connection.bridging_security_policy_ok(port_group):
                return True, (
                    f"Trunk port group '{name}': promiscuous mode, MAC address "
                    f"changes and forged transmits are accepted"
                )
        except Exception as exc:  # noqa: BLE001 - best effort or a check: the failure becomes a result or a warning, never a crash
            return (
                False,
                f"Trunk port group '{name}': security policy could not be checked ({exc})",
            )
        return False, (
            f"Trunk port group '{name}': security policy rejects promiscuous mode, "
            f"MAC address changes or forged transmits - bridged traffic between GNS3 "
            f"nodes and ESXi VMs is dropped"
        )

    def _repair_trunk_security_policy(self) -> list[str]:
        """
        Sets the trunk port group's security policy to accept promiscuous mode, MAC address
        changes and forged transmits - only if that port group exists and deviates (a
        missing port group is a matter for a deploy, not for this cheap repair).
        :return: what was done (empty if nothing was needed or possible)
        """
        if Settings.ONLY_ON_GNS3 or Settings.IS_DRY_RUN:
            return []
        name = Settings.ESXI.TRUNK_PORT_GROUP
        try:
            port_group = self.esxi_connection.find_port_group(name)
            if port_group is None or self.esxi_connection.bridging_security_policy_ok(
                port_group
            ):
                return []
            self.esxi_connection.ensure_bridging_security_policy(name)
        except Exception as exc:  # noqa: BLE001 - best effort or a check: the failure becomes a result or a warning, never a crash
            logger.warning(f"Could not repair the security policy of '{name}': {exc}")
            return []
        return [
            (
                f"Set the security policy of trunk port group '{name}' to accept "
                f"promiscuous mode, MAC address changes and forged transmits"
            )
        ]

    def verify_graph(self, graph: Graph, project_name: str) -> list[tuple[bool, str]]:
        """
        Runs a structural health check against real infrastructure. This is
        NOT a connectivity/ping test - this project never assigns an IP
        address to any node from its own config, so there is no address to
        ping for either side of an edge. Checks: the GNS3 VM's trunk NIC is
        wired to ``Settings.ESXI.TRUNK_PORT_GROUP``; every GNS3-hosted node
        is 'started'; every ESXi-hosted VM is powered on (its IP via VMware
        Tools, if any, is reported for information only - a topology's VLAN
        has no DHCP server, so a VM not reporting one is normal, not a
        failure); both sides of a direct ESXi-ESXi link agree on
        VLAN ID; an ESXi<->GNS3 bridge's Cloud node exists (named after the
        ESXi node, per create_node's own convention); and a GNS3-internal
        link actually exists between the two node IDs; and the trunk port
        group accepts promiscuous mode, MAC address changes and forged
        transmits (skipped with ``Settings.ONLY_ON_GNS3``).
        :param graph: built topology to verify
        :param project_name: name of the GNS3 project to check
        :return: list of (passed, description) tuples, one per check
        """
        results: list[tuple[bool, str]] = []
        self._adopt_esxi_vlan_ids(graph)
        port_groups = {
            pg["name"]: pg["vlan_id"] for pg in self.esxi_connection.list_port_groups()
        }
        results.extend(self._verify_port_group_vlan_ids(graph, port_groups))

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

        policy_result = self._verify_trunk_security_policy()
        if policy_result is not None:
            results.append(policy_result)

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
                    # A VM not reporting an IP is expected, not a failure -
                    # topology VLANs have no DHCP server, so most VMs never
                    # get one unless their OVA template has a static IP
                    # baked in. Reported for information only.
                    ip_address = self.esxi_connection.get_vm_ip_address(name)
                    if ip_address is None:
                        results.append(
                            (
                                True,
                                (
                                    f"ESXi VM '{name}': powered on, no IP reported "
                                    "(expected - topology VLANs have no DHCP)"
                                ),
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

                neighbour_interface = interface.peer or neighbour.get_interface(node)
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
                    wanted_ports = self._wanted_link_ports(
                        node_gns3, if_name, neighbour_gns3, neighbour_if_name
                    )
                    linked = any(
                        {endpoint["node_id"] for endpoint in link["nodes"]} == ids
                        and (
                            wanted_ports is None
                            or {
                                (
                                    endpoint["node_id"],
                                    endpoint.get("adapter_number"),
                                    endpoint.get("port_number"),
                                )
                                for endpoint in link["nodes"]
                            }
                            == wanted_ports
                        )
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
    def _wanted_link_ports(
        node_gns3: dict, if_name: str, neighbour_gns3: dict, neighbour_if_name: str
    ) -> set[tuple] | None:
        """
        The (node_id, adapter, port) endpoints a link between these two interfaces has, found by GNS3
        port name, so that of several links between the same two nodes the right one is checked.
        None if a port cannot be found by name (the check then only compares the two nodes).
        """

        def endpoint(gns3_node: dict, name: str):
            for port in gns3_node.get("ports", []):
                if str(port.get("name", "")).lower() == name.lower():
                    return (
                        gns3_node.get("node_id"),
                        port.get("adapter_number"),
                        port.get("port_number"),
                    )
            return None

        first = endpoint(node_gns3, if_name)
        second = endpoint(neighbour_gns3, neighbour_if_name)
        return {first, second} if first and second else None

    @staticmethod
    def _verify_port_group_vlan_ids(
        graph: Graph, port_groups: dict[str, int]
    ) -> list[tuple[bool, str]]:
        """
        Compares the VLAN id of each existing port group of the graph with the id the graph expects, and looks for
        two port groups of the graph that share one id (an unwanted Layer-2 connection). Only problems are reported
        - a consistent topology adds no result line.
        :param graph: the graph, its VLAN ids already adjusted to the ESXi ones (``_adopt_esxi_vlan_ids``)
        :param port_groups: name -> VLAN id of the port groups on the vSwitch
        :return: one failed (False, description) per problem
        """
        failures: list[tuple[bool, str]] = []
        names_by_id: dict[int, list[str]] = {}
        for vlan in graph.vlans():
            actual = port_groups.get(vlan.name)
            if actual is None:
                continue
            names_by_id.setdefault(actual, []).append(vlan.name)
            if actual != vlan.id:
                failures.append(
                    (
                        False,
                        (
                            f"Port group '{vlan.name}': VLAN id {actual} on ESXi, but the topology expects {vlan.id} "
                            f"- the link is on the wrong VLAN; verify --fix re-tags it"
                        ),
                    )
                )
        for actual, names in names_by_id.items():
            if len(names) > 1:
                quoted = ", ".join(f"'{name}'" for name in names)
                failures.append(
                    (
                        False,
                        (
                            f"Port groups {quoted} share VLAN id {actual} - an unwanted Layer-2 connection "
                            f"between different links; verify --fix gives all but one a free id"
                        ),
                    )
                )
        return failures

    def find_orphans(self, graph: Graph, project_name: str) -> list[dict[str, str]]:
        """
        Detects live GNS3 nodes and ESXi VMs that don't correspond to any
        node in the given graph - the state a live node/link delete
        (TopologyBackend.remove_node/remove_link, used by TopologyOperator)
        can leave behind when it partially fails, e.g. the GNS3-side
        delete succeeds but the following ESXi VM delete times out (or
        vice versa): the topology YAML gets updated either way only once
        both steps succeed, so a partial failure leaves a real, live
        resource with nothing in the topology file describing it anymore.
        Read-only - see delete_orphans to actually remove what this finds.
        :param graph: the topology that should currently be deployed
        :param project_name: name of the GNS3 project to check
        :return: list of {"type": "gns3_node" | "esxi_vm", "name": ..., "reason": ...}
        """
        orphans: list[dict[str, str]] = []
        known_names = set(graph.nodes)

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
        if project is not None:
            for gns3_node in GNS3Connection.list_project_nodes(
                self.gns3_vm_ip, Settings.GNS3.PORT, project["project_id"]
            ):
                name = gns3_node.get("name")
                if name not in known_names:
                    orphans.append(
                        {
                            "type": "gns3_node",
                            "name": name,
                            "reason": f"GNS3 node '{name}' exists in project "
                            f"'{project_name}' but has no matching node in "
                            f"the topology file",
                        }
                    )

        gns3_vm = self.esxi_connection.find_gns3_vm()
        gns3_vm_name = gns3_vm.name if gns3_vm is not None else None
        for vm in self.esxi_connection.get_all_vms():
            if vm.name == gns3_vm_name:
                continue
            annotation = vm.config.annotation or ""
            if not annotation.startswith("topologybuilder-image:"):
                continue
            base_name = re.sub(r"[ _]\(?\d+\)?$", "", vm.name)
            if base_name in known_names:
                continue
            orphans.append(
                {
                    "type": "esxi_vm",
                    "name": vm.name,
                    "reason": f"ESXi VM '{vm.name}' is tagged as created by "
                    f"this tool but has no matching node in the topology "
                    f"file",
                }
            )
        return orphans

    def delete_orphans(self, orphans: list[dict[str, str]], project_name: str) -> None:
        """
        Deletes every orphan find_orphans previously reported. Re-resolves
        the live project/node/VM list itself rather than trusting any
        node_id captured by an earlier find_orphans call, since an orphan
        list is often reviewed by a human (or held by a CLI's --fix flag
        for a moment) before anything is actually deleted, and live state
        can move in between.
        :param orphans: exactly what find_orphans returned (or a subset of it)
        :param project_name: name of the GNS3 project the gns3_node orphans belong to
        :return:
        """
        gns3_orphan_names = {o["name"] for o in orphans if o["type"] == "gns3_node"}
        if gns3_orphan_names:
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
            if project is not None:
                for gns3_node in GNS3Connection.list_project_nodes(
                    self.gns3_vm_ip, Settings.GNS3.PORT, project["project_id"]
                ):
                    if gns3_node.get("name") in gns3_orphan_names:
                        GNS3Connection.delete_node(
                            self.gns3_vm_ip,
                            Settings.GNS3.PORT,
                            project["project_id"],
                            gns3_node["node_id"],
                        )

        esxi_orphan_names = {o["name"] for o in orphans if o["type"] == "esxi_vm"}
        if esxi_orphan_names:
            for vm in self.esxi_connection.get_all_vms():
                if vm.name in esxi_orphan_names:
                    self.esxi_connection.delete_vm(vm)

    def repair_graph(self, graph: Graph, project_name: str) -> list[str]:
        """
        Applies a curated, low-risk subset of automatic fixes for issues
        verify_graph can detect: powers on an ESXi VM that exists but
        isn't powered on, starts a GNS3 node that exists but isn't
        started, creates a missing port group for an interface whose
        VLAN doesn't have one yet, and sets an existing trunk port group's
        security policy to accept promiscuous mode/MAC changes/forged
        transmits if it deviates. Deliberately does NOT attempt anything
        that would require redeploying a genuinely missing VM/node or
        recreating a missing Cloud-node bridge - those need a real
        OVA/template import, which is too consequential to trigger from a
        read-mostly repair pass; run `deploy --incremental` for that
        instead, or find_orphans/delete_orphans above for genuinely
        leftover (rather than missing) resources.
        :param graph: the topology that should currently be deployed
        :param project_name: name of the GNS3 project to check
        :return: human-readable description of each fix actually applied, in order
        """
        actions: list[str] = []
        self._adopt_esxi_vlan_ids(graph)

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
        gns3_nodes_by_name: dict[str, dict] = {}
        if project is not None:
            gns3_nodes_by_name = {
                gns3_node.get("name"): gns3_node
                for gns3_node in GNS3Connection.list_project_nodes(
                    self.gns3_vm_ip, Settings.GNS3.PORT, project["project_id"]
                )
            }

        for name, node in graph.nodes.items():
            if node.env == Environment.ON_GNS3:
                gns3_node = gns3_nodes_by_name.get(name)
                if gns3_node is not None and gns3_node.get("status") != "started":
                    GNS3Connection.start_node(
                        self.gns3_vm_ip,
                        Settings.GNS3.PORT,
                        project["project_id"],
                        gns3_node["node_id"],
                    )
                    actions.append(f"Started GNS3 node '{name}'")
            elif node.env == Environment.ON_ESXI:
                vm = self.esxi_connection.get_vm(name)
                if vm is not None and not self.esxi_connection.is_vm_powered_on(vm):
                    self.esxi_connection.power_on_vm(vm)
                    actions.append(f"Powered on ESXi VM '{name}'")

        try:
            port_group_ids = {
                pg["name"]: pg["vlan_id"]
                for pg in self.esxi_connection.list_port_groups()
            }
        except ValueError:  # no vSwitch yet: no port group to compare
            port_group_ids = {}
        seen_vlan_ids: set[int] = set()
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                vlan = interface.vlan
                if vlan is None or vlan.id in seen_vlan_ids:
                    continue
                seen_vlan_ids.add(vlan.id)
                if self.esxi_connection.find_port_group(vlan.name) is None:
                    self.esxi_connection._add_port_group(vlan)
                    actions.append(
                        f"Created missing port group '{vlan.name}' (VLAN {vlan.id})"
                    )
                elif port_group_ids.get(vlan.name, vlan.id) != vlan.id:
                    self.esxi_connection._add_port_group(vlan, fix_vlan=True)
                    actions.append(
                        f"Re-tagged port group '{vlan.name}' from VLAN {port_group_ids[vlan.name]} to VLAN {vlan.id}"
                        " (run a deploy --incremental to move the Cloud node's port and the GNS3 VM's subinterface along)"
                    )

        actions.extend(self._repair_trunk_security_policy())
        return actions

    @staticmethod
    def _partially_link_gns3_nodes(gns3_connection: GNS3Connection, node) -> None:
        """
        Links only those nodes to this node who already exist on GNS3. An
        edge between two ESXi-hosted nodes is skipped - both VMs' vNICs
        already share one port group directly at the ESXi layer (see
        Graph._assign_vlans), so no GNS3-side link is needed or wanted.
        Each node still gets its own Cloud node in GNS3 for any *other*
        edges it has; linking two Cloud nodes together for a direct
        ESXi-ESXi edge would be redundant and GNS3 rejects it outright
        (409 Conflict) - and if a node's edges are *all* direct ESXi-ESXi
        links, it has no Cloud node at all (see GNS3Connection.create_node),
        so this loop's neighbour.gns3_node_info check naturally skips it
        too.
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
            if node.env == Environment.ON_ESXI and neighbour.env == Environment.ON_ESXI:
                continue
            gns3_connection.connect_nodes(
                node,
                neighbour,
                node.interfaces[interface],
                node.interfaces[interface].peer,
            )

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

        gns3_interface_setup = self._open_gns3_interface_setup(
            gns3_username, gns3_password
        )
        gns3_interface_setup.initialize_commands(graph)
        gns3_interface_setup.execute_script()

    def _open_gns3_interface_setup(
        self, gns3_username: str, gns3_password: str | None
    ) -> GNS3VMInterfaceSetup:
        port = 22

        gns3_connection = SSHConnection(
            self.gns3_vm_ip, port, gns3_username, gns3_password
        )
        parent_interface = self._resolve_gns3_parent_interface(gns3_connection)
        return GNS3VMInterfaceSetup(gns3_connection, parent_interface)

    def verify_vlan_subinterfaces(
        self, graph: Graph, gns3_username: str, gns3_password: str | None
    ) -> tuple[bool, str]:
        """
        Checks that every VLAN subinterface the graph needs exists on the GNS3 VM. They are lost
        when that VM reboots (plain ``ip link`` objects), and without them every link between a
        GNS3 node and an ESXi VM carries no traffic although all other checks pass.
        :return: (passed, description)
        """
        if Settings.ONLY_ON_ESXI:
            return True, "GNS3 VM VLAN subinterfaces: not needed (ESXi only)"
        self._adopt_esxi_vlan_ids(graph)
        try:
            if not GNS3VMInterfaceSetup.expected_subinterfaces(graph):
                return True, "GNS3 VM VLAN subinterfaces: none needed by this topology"
            setup = self._open_gns3_interface_setup(gns3_username, gns3_password)
            missing = setup.missing_subinterfaces(graph)
            total = len(setup.expected_subinterfaces(graph))
        except Exception as exc:  # noqa: BLE001 - best effort or a check: the failure becomes a result or a warning, never a crash
            return False, f"GNS3 VM VLAN subinterfaces: could not be checked ({exc})"
        if missing:
            return (
                False,
                (
                    f"GNS3 VM VLAN subinterfaces: {len(missing)} of {total} missing "
                    f"({', '.join(missing)}) - links to ESXi VMs carry no traffic; re-creating them is a separate, "
                    f"explicit step (--fix-vlan-subinterfaces), see the warning there"
                ),
            )
        return True, f"GNS3 VM VLAN subinterfaces: all {total} present"

    def verify_persistent_vlan_config(
        self, graph: Graph, gns3_username: str, gns3_password: str | None
    ) -> tuple[bool, str]:
        """
        Checks that the GNS3 VM re-creates its VLAN subinterfaces by itself after a reboot (the managed
        boot-time service written at deploy), so the topology survives a restart of that VM.
        :return: (passed, description)
        """
        if Settings.ONLY_ON_ESXI:
            return True, "GNS3 VM boot-time VLAN service: not needed (ESXi only)"
        self._adopt_esxi_vlan_ids(graph)
        try:
            setup = self._open_gns3_interface_setup(gns3_username, gns3_password)
            problem = setup.persistent_config_problem(graph)
        except Exception as exc:  # noqa: BLE001 - best effort or a check: the failure becomes a result or a warning, never a crash
            return (
                False,
                f"GNS3 VM boot-time VLAN service: could not be checked ({exc})",
            )
        if problem:
            return (
                False,
                (
                    f"GNS3 VM boot-time VLAN service: {problem} - after a reboot of the GNS3 VM the "
                    f"subinterfaces would be gone; verify --fix writes it (touches no running link)"
                ),
            )
        return True, "GNS3 VM boot-time VLAN service: installed and up to date"

    def install_persistent_vlan_config(
        self, graph: Graph, gns3_username: str, gns3_password: str | None
    ) -> list[str]:
        """
        Writes the managed boot-time service (see verify_persistent_vlan_config). Starts and restarts
        nothing, so it is part of the normal automatic repairs.
        :return: what was done (empty if it was already up to date)
        """
        if Settings.ONLY_ON_ESXI:
            return []
        self._adopt_esxi_vlan_ids(graph)
        setup = self._open_gns3_interface_setup(gns3_username, gns3_password)
        if not setup.install_persistent_config(graph):
            return []
        return ["Wrote the boot-time VLAN subinterface service on the GNS3 VM"]

    def repair_vlan_subinterfaces(
        self,
        graph: Graph,
        project_name: str,
        gns3_username: str,
        gns3_password: str | None,
    ) -> list[str]:
        """
        Re-creates the missing VLAN subinterfaces on the GNS3 VM (see verify_vlan_subinterfaces)
        and restarts the Cloud nodes of the ESXi VMs so they bind to them again. Existing
        subinterfaces are left alone.
        :return: human-readable description of what was done (empty if nothing was missing)
        """
        if Settings.ONLY_ON_ESXI:
            return []
        self._adopt_esxi_vlan_ids(graph)
        if not GNS3VMInterfaceSetup.expected_subinterfaces(graph):
            return []
        setup = self._open_gns3_interface_setup(gns3_username, gns3_password)
        created = setup.create_missing_subinterfaces(graph)
        if not created:
            return []
        if Settings.IS_DRY_RUN:
            return [
                f"Would re-create VLAN subinterface {name} on the GNS3 VM"
                for name in created
            ]
        actions = [
            f"Re-created VLAN subinterface {name} on the GNS3 VM" for name in created
        ]
        actions.extend(self._restart_cloud_nodes(graph, project_name))
        return actions

    def _restart_cloud_nodes(self, graph: Graph, project_name: str) -> list[str]:
        """Stops and starts the Cloud node of every ESXi VM that is bridged to a GNS3 node (it binds its interface when it starts)."""
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
            return []
        nodes_by_name = {
            n.get("name"): n
            for n in GNS3Connection.list_project_nodes(
                self.gns3_vm_ip, Settings.GNS3.PORT, project["project_id"]
            )
        }
        clouds: dict[str, dict[str, Any]] = {}
        for name, node in graph.nodes.items():
            if node.env != Environment.ON_ESXI:
                continue
            cloud = nodes_by_name.get(name)
            if cloud is not None and cloud.get("node_type") == "cloud":
                clouds[name] = cloud
        running = [
            name for name, cloud in clouds.items() if cloud.get("status") == "started"
        ]
        if running:
            # A Cloud that kept running while its subinterface was gone cannot bind to the new one: stopping and starting
            # it keeps its helper process (ubridge) and with it the dead binding. Closing the project ends the helpers.
            return self._reopen_project_for_clouds(
                project, list(nodes_by_name.values()), running
            )
        actions: list[str] = []
        for name, cloud in clouds.items():
            try:
                for method in (GNS3Connection.stop_node, GNS3Connection.start_node):
                    method(
                        self.gns3_vm_ip,
                        Settings.GNS3.PORT,
                        project["project_id"],
                        cloud["node_id"],
                    )
            except Exception as exc:  # noqa: BLE001 - best effort or a check: the failure becomes a result or a warning, never a crash
                # One stuck Cloud node must not hide that the subinterfaces
                # were already re-created, nor stop the others from restarting.
                logger.warning(f"Could not restart the Cloud node of '{name}': {exc}")
                actions.append(f"Could not restart the Cloud node of '{name}': {exc}")
                continue
            actions.append(f"Restarted the Cloud node of '{name}'")
        return actions

    def _reopen_project_for_clouds(
        self,
        project: dict[str, Any],
        project_nodes: list[dict[str, Any]],
        running_clouds: list[str],
    ) -> list[str]:
        """
        Closes and opens the GNS3 project so that running Cloud nodes bind to the re-created subinterfaces, then starts
        again every node that was running before. This also restarts the other running nodes of the project (a closed
        project stops all of them), which the returned text says.
        """
        running = [n for n in project_nodes if n.get("status") == "started"]
        names = ", ".join(f"'{name}'" for name in running_clouds)
        try:
            GNS3Connection.close_project(
                self.gns3_vm_ip, Settings.GNS3.PORT, project["project_id"]
            )
            GNS3Connection.ensure_project_open(
                self.gns3_vm_ip, Settings.GNS3.PORT, project["project_id"]
            )
        except Exception as exc:  # noqa: BLE001 - a check or a repair: the failure becomes a result, never a crash
            logger.warning(f"Could not re-open the GNS3 project for the Clouds: {exc}")
            return [
                f"Could not re-open the GNS3 project to rebind the Cloud node(s) of {names}: {exc}"
            ]
        actions = [
            f"Re-opened the GNS3 project to rebind the running Cloud node(s) of {names} "
            f"(this stopped {len(running)} running node(s); they are started again)"
        ]
        # the Clouds first: the nodes behind them need their link, and the order of the others does not matter
        cloud_ids = {n["node_id"] for n in running if n.get("node_type") == "cloud"}
        for node in sorted(running, key=lambda n: n["node_id"] not in cloud_ids):
            try:
                GNS3Connection.start_node(
                    self.gns3_vm_ip,
                    Settings.GNS3.PORT,
                    project["project_id"],
                    node["node_id"],
                )
            except Exception as exc:  # noqa: BLE001 - one node that does not start must not stop the others
                logger.warning(
                    f"Could not start node '{node.get('name')}' again: {exc}"
                )
                actions.append(
                    f"Could not start node '{node.get('name')}' again: {exc}"
                )
        return actions

    def _resolve_gns3_parent_interface(self, gns3_ssh_connection: SSHConnection) -> str:
        """
        Resolves the guest-OS interface name on the GNS3 VM that carries
        the VLAN trunk, for GNS3VMInterfaceSetup to create subinterfaces
        on. If ``Settings.GNS3.PARENT_INTERFACE`` is set explicitly,
        returns it unchanged - no detection attempted. Otherwise, detects
        it by MAC address: looks up which of the GNS3 VM's own vNICs (on
        the ESXi side) is wired to ``Settings.ESXI.TRUNK_PORT_GROUP``,
        then SSHes into the GNS3 VM to find the guest-OS interface with
        that same MAC - the interface *name* isn't guaranteed to match
        any particular convention across different GNS3 VM builds (e.g.
        'eth1' vs. 'ens192'), but the MAC does.
        :param gns3_ssh_connection: SSH connection to the GNS3 VM
        :return: the resolved interface name
        :raises RuntimeError: Is thrown when no vNIC on the GNS3 VM is wired to the trunk port group, or when no guest-OS interface with that MAC can be found.
        """
        if Settings.GNS3.PARENT_INTERFACE is not None:
            return Settings.GNS3.PARENT_INTERFACE

        gns3_vm = self.esxi_connection.get_vm(self.gns3_vm_name)
        mac_address = self.esxi_connection.find_vm_nic_mac_by_port_group(
            gns3_vm, Settings.ESXI.TRUNK_PORT_GROUP
        )
        if mac_address is None:
            raise RuntimeError(
                f"Could not auto-detect the GNS3 VM's trunk interface: no "
                f"NIC on '{self.gns3_vm_name}' is wired to trunk port group "
                f"'{Settings.ESXI.TRUNK_PORT_GROUP}'. Set "
                f"gns3.parent_interface explicitly in settings.yml instead."
            )

        mac = mac_address.lower()
        # Excludes '@'-suffixed names (e.g. 'PC4_gi0-0@eth1') - a VLAN
        # subinterface inherits its parent's MAC address by default, so
        # any leftover subinterface from an earlier deploy would
        # otherwise also match and produce multiple candidates.
        _, stdout, _ = gns3_ssh_connection.exec_command(
            f"ip -br link show | awk 'tolower($3) == \"{mac}\" && $1 !~ /@/ {{print $1}}'"
        )
        output = stdout.read().decode().strip()
        interface_names = [line for line in output.splitlines() if line]
        if len(interface_names) != 1:
            raise RuntimeError(
                f"Could not auto-detect the GNS3 VM's trunk interface: "
                f"expected exactly one guest-OS interface with MAC "
                f"{mac_address} on '{self.gns3_vm_name}', found "
                f"{interface_names or 'none'}. Set gns3.parent_interface "
                f"explicitly in settings.yml instead."
            )
        interface_name = interface_names[0]
        logger.info(
            f"Auto-detected GNS3 VM trunk interface '{interface_name}' "
            f"(MAC {mac_address})"
        )
        return interface_name

    def _log_console_port_collision_diagnostics(
        self, gns3_username: str, gns3_password: str | None
    ) -> None:
        """
        Best-effort diagnostic capture for a console-port-collision
        failure that survived GNS3Connection.start_all_nodes' own retry -
        SSHes into the GNS3 VM to record which process is actually
        holding the console port, so the next occurrence leaves real
        evidence in the logs instead of only a presumed cause. Never
        raises - a failed diagnostic attempt must not mask the real
        deploy error it was trying to help explain.
        :param gns3_username: username to connect to the GNS3 VM via SSH
        :param gns3_password: password to connect to the GNS3 VM via SSH
        :return:
        """
        try:
            gns3_connection = SSHConnection(
                self.gns3_vm_ip, 22, gns3_username, gns3_password
            )
            for command in ("ss -tlnp", "ps aux | grep qemu"):
                _, stdout, _ = gns3_connection.exec_command(command)
                output = stdout.read().decode().strip()
                logger.error(
                    f"Console port collision diagnostics - '{command}':\n{output}"
                )
        except Exception as diagnostic_error:  # noqa: BLE001 - best effort or a check: the failure becomes a result or a warning, never a crash
            logger.warning(
                f"Could not capture console port collision diagnostics: "
                f"{diagnostic_error}"
            )
