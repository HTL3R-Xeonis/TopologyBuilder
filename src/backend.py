"""
A clean, library-level API for operating an already-deployed topology
one node/link at a time - as opposed to src/cli.py's deploy/destroy,
which always operate on a whole topology file at once. Built for
TopologyOperator (a separate project depending on this one as a
library) to add/remove nodes and links live, synced back into the
topology YAML, without reaching into ESXiConnection/GNS3Connection/
VMOrchestrator/Graph internals directly.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from src.connections.gns3_connection import GNS3Connection
from src.graph import Environment, Graph
from src.graph.blocks.generic_node import GenericNode
from src.settings import Settings
from src.topology_file_validation import TopologyFileValidation
from src.vm_orchestrator.vm_orchestrator import VMOrchestrator


class TopologyBackend:
    """
    Wraps one VMOrchestrator (and the ESXi/GNS3 connections it holds) to
    add/remove nodes and links against an already-deployed topology,
    keeping the topology YAML file in sync with each change.
    """

    def __init__(
        self,
        esxi_host: str,
        esxi_port: int,
        esxi_username: str,
        esxi_password: str | None,
        gns3_vm_name: str,
        gns3_username: str,
        gns3_password: str | None = None,
        gns3_port: int = 80,
    ) -> None:
        """
        :param esxi_host: IPv4 address of the ESXi host.
        :param esxi_port: Port number of the ESXi host's API.
        :param esxi_username: ESXi username.
        :param esxi_password: ESXi password.
        :param gns3_vm_name: Name of the GNS3 VM on the ESXi host.
        :param gns3_username: Username for the GNS3 VM.
        :param gns3_password: Password for the GNS3 VM.
        :param gns3_port: Port of the GNS3 VM's API.
        :raises RuntimeError: Is thrown when the GNS3 VM is not found on the ESXi host.
        :raises ValueError: Is thrown when invalid credentials are provided.
        :raises TimeoutError: Is thrown when timeout occurs.
        :raises ConnectionError: Is thrown when the connection buildup fails.
        """
        self._orchestrator = VMOrchestrator(
            esxi_host, esxi_port, esxi_username, esxi_password, gns3_vm_name
        )
        self._gns3_username = gns3_username
        self._gns3_password = gns3_password
        self._gns3_port = gns3_port

    def _load(self, topology_file: str) -> tuple[TopologyFileValidation, Graph]:
        validator = TopologyFileValidation(topology_file)
        validator.validate_file()
        return validator, Graph(validator.nodes, validator.edges)

    def _set_project_name(self, topology_file: str) -> str:
        """
        deploy_graph reads Settings.GNS3.PROJECT_NAME globally rather
        than taking it as a parameter (same as src/cli.py's own deploy
        command) - resolved fresh from topology_file's own stem every
        call (mirrors cli.py's private _resolve_project_name), not
        cached, so a backend instance can safely be reused across
        different topology files.
        """
        name = Settings.GNS3.PROJECT_NAME or Path(topology_file).stem
        Settings.GNS3.PROJECT_NAME = name
        return name

    def _resolve_live_project_id(self, project_name: str) -> str | None:
        projects = GNS3Connection.list_all_projects(
            self._orchestrator.gns3_vm_ip, self._gns3_port
        )
        project = next((p for p in projects if p["name"] == project_name), None)
        return project["project_id"] if project is not None else None

    def _validate_and_build_graph(self, validator: TopologyFileValidation) -> Graph:
        """
        Validates a validator's in-memory (not yet saved) nodes/edges
        and builds the resulting Graph - without ever touching the real
        topology file. TopologyFileValidation.validate_file() always
        re-reads from its own path on disk, so the only way to validate
        an in-memory change is to point a throwaway validator at a
        disposable temp file holding that same content. This lets
        add_node/add_link validate+deploy the new state before ever
        writing the real topology_file, so a failed deploy leaves it
        untouched (see add_node's own docstring).
        :raises ValueError: propagated from validate_file() - e.g. an invalid role or image.
        """
        fd, tmp_path = tempfile.mkstemp(suffix=".yaml")
        try:
            with os.fdopen(fd, "w") as file:
                yaml.safe_dump(
                    {"nodes": validator.nodes, "edges": validator.edges},
                    file,
                    sort_keys=False,
                )
            tmp_validator = TopologyFileValidation(tmp_path)
            tmp_validator.validate_file()
            return Graph(tmp_validator.nodes, tmp_validator.edges)
        finally:
            os.unlink(tmp_path)

    def add_node(
        self, topology_file: str, name: str, role: str, image: str
    ) -> GenericNode:
        """
        Deploys a new node live (incrementally - existing nodes/links
        are left untouched, but see VMOrchestrator.deploy_graph's own
        docstring: every VLAN subinterface on the GNS3 VM's trunk NIC
        still gets briefly torn down and recreated on every call, even
        for one new node) and only then adds it to the topology YAML.
        Live deployment happens first, so a failure there leaves the
        YAML file unchanged rather than claiming a node exists that was
        never actually deployed.
        :param topology_file: path to the topology YAML file
        :param name: name of the new node
        :param role: role of the new node, e.g. "ROUTER"
        :param image: image/template name of the new node
        :return: the new node, as it exists in the freshly-built Graph
        :raises ValueError: if a node with this name already exists, or the image doesn't exist on GNS3/ESXi.
        :raises RuntimeError: propagated from VMOrchestrator.deploy_graph on deploy failure.
        """
        validator, graph = self._load(topology_file)
        if name in graph.nodes:
            raise ValueError(f"node {name!r} already exists in {topology_file}")

        validator.add_node(name, role, image)
        graph = self._validate_and_build_graph(validator)

        self._set_project_name(topology_file)
        self._orchestrator.deploy_graph(
            graph, self._gns3_username, self._gns3_password, incremental=True
        )

        validator.save()
        return graph.nodes[name]

    def add_link(
        self, topology_file: str, node1: str, if1: str, node2: str, if2: str
    ) -> None:
        """
        Connects two nodes live (incrementally - see add_node's
        docstring for the same VLAN-subinterface caveat) and only then
        adds the edge to the topology YAML. Live deployment happens
        first, so a failure there leaves the YAML file unchanged rather
        than claiming an edge exists that was never actually deployed.
        :param topology_file: path to the topology YAML file
        :param node1: name of the first node
        :param if1: interface name on the first node
        :param node2: name of the second node
        :param if2: interface name on the second node
        :return:
        :raises ValueError: if either node doesn't exist, or the interface is already in use.
        :raises RuntimeError: propagated from VMOrchestrator.deploy_graph on deploy failure.
        """
        validator, _ = self._load(topology_file)
        validator.add_edge(node1, if1, node2, if2)
        graph = self._validate_and_build_graph(validator)

        self._set_project_name(topology_file)
        self._orchestrator.deploy_graph(
            graph, self._gns3_username, self._gns3_password, incremental=True
        )

        validator.save()

    def remove_node(self, topology_file: str, name: str) -> None:
        """
        Deletes a node live (its GNS3 node if one exists, its ESXi VM if
        it's ON_ESXI) and removes it - and any edge referencing it -
        from the topology YAML. Live deletion happens first, so a
        failure there leaves the YAML still accurately describing what's
        actually deployed rather than claiming something's gone that
        isn't.
        :param topology_file: path to the topology YAML file
        :param name: name of the node to remove
        :return:
        :raises ValueError: if no node with this name exists in the topology file.
        :raises RuntimeError: propagated from GNS3Connection.delete_node on deletion failure.
        """
        validator, graph = self._load(topology_file)
        node = graph.nodes.get(name)
        if node is None:
            raise ValueError(f"no node named {name!r} in {topology_file}")

        project_name = self._set_project_name(topology_file)
        project_id = self._resolve_live_project_id(project_name)
        if project_id is not None:
            live_node = next(
                (
                    n
                    for n in GNS3Connection.list_project_nodes(
                        self._orchestrator.gns3_vm_ip, self._gns3_port, project_id
                    )
                    if n["name"] == name
                ),
                None,
            )
            if live_node is not None:
                GNS3Connection.delete_node(
                    self._orchestrator.gns3_vm_ip,
                    self._gns3_port,
                    project_id,
                    live_node["node_id"],
                )

        if node.env == Environment.ON_ESXI:
            vm = self._orchestrator.esxi_connection.get_vm(name)
            if vm is not None:
                self._orchestrator.esxi_connection.delete_vm(vm)

        validator.remove_node(name)
        validator.save()

    def remove_link(self, topology_file: str, node1: str, node2: str) -> None:
        """
        Deletes the live GNS3 link directly connecting node1 and node2
        (if one exists) and removes the corresponding edge from the
        topology YAML. See remove_node - live deletion happens first.
        :param topology_file: path to the topology YAML file
        :param node1: name of one endpoint node
        :param node2: name of the other endpoint node
        :return:
        :raises RuntimeError: propagated from GNS3Connection.delete_link on deletion failure.
        """
        validator, _ = self._load(topology_file)

        project_name = self._set_project_name(topology_file)
        project_id = self._resolve_live_project_id(project_name)
        if project_id is not None:
            gns3_vm_ip = self._orchestrator.gns3_vm_ip
            live_nodes = GNS3Connection.list_project_nodes(
                gns3_vm_ip, self._gns3_port, project_id
            )
            node_ids = {
                n["name"]: n["node_id"] for n in live_nodes if n["name"] in (node1, node2)
            }
            if node1 in node_ids and node2 in node_ids:
                wanted = {node_ids[node1], node_ids[node2]}
                live_links = GNS3Connection.list_project_links(
                    gns3_vm_ip, self._gns3_port, project_id
                )
                link = next(
                    (
                        candidate
                        for candidate in live_links
                        if {
                            endpoint["node_id"] for endpoint in candidate["nodes"]
                        }
                        == wanted
                    ),
                    None,
                )
                if link is not None:
                    GNS3Connection.delete_link(
                        gns3_vm_ip, self._gns3_port, project_id, link["link_id"]
                    )

        validator.remove_edge(node1, node2)
        validator.save()
