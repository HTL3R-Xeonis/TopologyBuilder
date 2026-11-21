from collections import Counter
from typing import Any

import requests

from src.graph import Graph
from src.settings import Settings

from ..connections import APIHandler
from .status import Status, StatusList
from .topology_state import TopologyState


class GNS3Doctor:
    """Checks the running GNS3 server without changing its projects."""

    def __init__(self, ip: str, port: int) -> None:
        """
        Configures the GNS3 API endpoint.
        :param ip: GNS3 server IP address.
        :param port: GNS3 API port.
        """
        self.ip = ip
        self.port = port
        self.url = f"http://{ip}:{port}"

    def _get(self, endpoint: str) -> Any:
        """
        Retrieves a GNS3 API resource.
        :param endpoint: API endpoint path.
        :return: Decoded API response.
        :raises requests.RequestException: If the GNS3 API rejects the request.
        :raises TimeoutError: If the GNS3 API does not respond.
        :raises ValueError: If the response is not valid JSON.
        """
        return APIHandler.get(f"{self.url}{endpoint}")

    def check_setup(self) -> StatusList:
        """
        Checks the GNS3 API and reports its version.
        :return: GNS3 connectivity health-check results.
        """
        results = StatusList()
        try:
            version = self._get("/v2/version")
            results.add(Status.ok("GNS3", f"API reachable ({version.get('version', 'unknown version')})."))
        except (requests.RequestException, TimeoutError, ValueError, TypeError, AttributeError) as exc:
            results.add(Status.error("GNS3", f"API not reachable at {self.url}: {exc}"))
        return results

    def project_status(self) -> tuple[StatusList, list[dict]]:
        """
        Reports GNS3 projects and their running node counts.
        :return: Project health-check results and discovered projects.
        """
        results = self.check_setup()
        projects = []
        if results.has_failures:
            return results, projects
        try:
            response = self._get("/v2/projects")
            if not isinstance(response, list):
                raise TypeError("Invalid GNS3 project list")
            projects = response
            if not projects:
                results.add(Status.info("GNS3", "No projects found."))
            for project in projects:
                nodes = self._get(f"/v2/projects/{project['project_id']}/nodes")
                running = sum(node.get("status") == "started" for node in nodes)
                results.add(Status.info("GNS3 project", f"{project['name']}: {running}/{len(nodes)} nodes started."))
        except (requests.RequestException, TimeoutError, ValueError, KeyError, TypeError) as exc:
            results.add(Status.error("GNS3", f"Could not list projects: {exc}"))
        return results, projects

    def verify_graph(self, graph: Graph, state: TopologyState, project: dict | None) -> StatusList:
        """
        Checks expected GNS3 nodes and links against an infrastructure snapshot.
        :param graph: Desired topology.
        :param state: Inspected infrastructure.
        :param project: Existing project information, if any.
        :return: GNS3 topology health-check results.
        """
        results = StatusList()
        if project is None:
            results.add(Status.missing("GNS3 project", f"{Settings.GNS3.PROJECT_NAME} does not exist."))
            return results
        if project.get("status") == "closed":
            results.add(Status.fault("GNS3 project", f"{Settings.GNS3.PROJECT_NAME} is closed."))
        for conflict in state.conflicts:
            results.add(Status.fault("GNS3 project", conflict))

        by_id = {node.get("node_id"): node.get("name") for node in state.gns3_all_nodes}
        for name in graph.nodes:
            live = state.gns3_nodes.get(name)
            if live is None:
                results.add(Status.missing("GNS3 node", f"{name} does not exist in {Settings.GNS3.PROJECT_NAME}."))
            elif live.get("node_type") == "cloud" or live.get("status") == "started":
                results.add(Status.ok("GNS3 node", f"{name} exists and is ready."))
            else:
                results.add(Status.fault("GNS3 node", f"{name} is not started ({live.get('status', 'unknown')})."))

        expected = Counter()
        for node in graph.nodes.values():
            for interface in node.interfaces.values():
                neighbour = getattr(interface.neighbour, "name", None)
                if neighbour:
                    expected[tuple(sorted((node.name, neighbour)))] += 1
        expected = Counter({pair: count // 2 for pair, count in expected.items()})
        live_links = Counter()
        for link in state.gns3_links:
            endpoints = link.get("nodes", [])
            if len(endpoints) == 2:
                names = (by_id.get(endpoints[0].get("node_id")), by_id.get(endpoints[1].get("node_id")))
                if all(names):
                    live_links[tuple(sorted(names))] += 1
        for pair, count in expected.items():
            if live_links[pair] < count:
                results.add(
                    Status.missing("GNS3 link", f"{' <-> '.join(pair)}: {live_links[pair]}/{count} links exist.")
                )
            else:
                results.add(Status.ok("GNS3 link", f"{' <-> '.join(pair)}: {count} links exist."))
        return results

    def find_orphans(self, graph: Graph, state: TopologyState, project: dict | None) -> StatusList:
        """
        Reports GNS3 nodes absent from the expected topology.
        :param graph: Desired topology.
        :param state: Inspected infrastructure.
        :param project: Existing project information, if any.
        :return: Possible orphan health-check results.
        """
        results = StatusList()
        if project is None:
            results.add(Status.missing("GNS3 project", f"{Settings.GNS3.PROJECT_NAME} does not exist."))
            return results
        for node in state.gns3_all_nodes:
            if node.get("name") not in graph.nodes:
                results.add(Status.fault("Possible orphan", f"GNS3 node {node.get('name')} is not in the topology."))
        for conflict in state.conflicts:
            results.add(Status.fault("GNS3 project", conflict))
        return results
