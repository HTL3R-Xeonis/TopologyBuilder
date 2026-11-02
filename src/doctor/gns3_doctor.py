from collections import Counter

import requests

from src.graph import Graph
from src.settings import Settings

from .status import Status, StatusList


class GNS3Doctor:
    """Checks the running GNS3 server without changing its projects."""

    def __init__(self, ip: str, port: int) -> None:
        """Configures the GNS3 API endpoint."""
        self.url = f"http://{ip}:{port}"

    def _get(self, endpoint: str):
        """Reads a GNS3 API resource."""
        response = requests.get(f"{self.url}{endpoint}", timeout=5)
        response.raise_for_status()
        return response.json()

    def check_setup(self) -> StatusList:
        """Checks the GNS3 API and reports its version."""
        results = StatusList()
        try:
            version = self._get("/v2/version")
            results.add(Status.ok("GNS3", f"API reachable ({version.get('version', 'unknown version')})."))
        except (requests.RequestException, ValueError) as exc:
            results.add(Status.error("GNS3", f"API not reachable at {self.url}: {exc}"))
        return results

    def project_status(self) -> tuple[StatusList, list[dict]]:
        """Reports GNS3 projects and their running node counts."""
        results = self.check_setup()
        projects = []
        if results.has_failures:
            return results, projects
        try:
            projects = self._get("/v2/projects")
            if not projects:
                results.add(Status.info("GNS3", "No projects found."))
            for project in projects:
                nodes = self._get(f"/v2/projects/{project['project_id']}/nodes")
                running = sum(node.get("status") == "started" for node in nodes)
                results.add(Status.info("GNS3 project", f"{project['name']}: {running}/{len(nodes)} nodes started."))
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            results.add(Status.error("GNS3", f"Could not list projects: {exc}"))
        return results, projects

    def verify_graph(self, graph: Graph) -> StatusList:
        """Checks GNS3 nodes and links against the topology."""
        results = StatusList()
        try:
            projects = self._get("/v2/projects")
            project = next((item for item in projects if item["name"] == Settings.GNS3.PROJECT_NAME), None)
            if project is None:
                results.add(Status.missing("GNS3 project", f"{Settings.GNS3.PROJECT_NAME} does not exist."))
                return results
            project_path = f"/v2/projects/{project['project_id']}"
            nodes = self._get(f"{project_path}/nodes")
            links = self._get(f"{project_path}/links")
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            results.add(Status.error("GNS3", f"Could not inspect deployed topology: {exc}"))
            return results

        by_name = {node.get("name"): node for node in nodes}
        by_id = {node.get("node_id"): node.get("name") for node in nodes}
        for name in graph.nodes:
            live = by_name.get(name)
            if live is None:
                results.add(Status.missing("GNS3 node", f"{name} does not exist in {Settings.GNS3.PROJECT_NAME}."))
            elif live.get("node_type") == "cloud" or live.get("status") == "started":
                results.add(Status.ok("GNS3 node", f"{name} exists and is ready."))
            else:
                results.add(Status.fault("GNS3 node", f"{name} is not started ({live.get('status', 'unknown')})."))

        # Verify link multiplicity; both ESXi Cloud nodes and regular nodes use graph names.
        expected = Counter()
        for node in graph.nodes.values():
            for intf in node.interfaces.values():
                neighbor = getattr(intf.neighbour, "name", None)
                if neighbor:
                    expected[tuple(sorted((node.name, neighbor)))] += 1
        expected = Counter({pair: count // 2 for pair, count in expected.items()})
        live_links = Counter()
        for link in links:
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

    def find_orphans(self, graph: Graph) -> StatusList:
        """Reports GNS3 nodes absent from the topology file."""
        results = StatusList()
        try:
            projects = self._get("/v2/projects")
            project = next((item for item in projects if item["name"] == Settings.GNS3.PROJECT_NAME), None)
            if project is None:
                results.add(Status.missing("GNS3 project", f"{Settings.GNS3.PROJECT_NAME} does not exist."))
                return results
            nodes = self._get(f"/v2/projects/{project['project_id']}/nodes")
            for node in nodes:
                if node.get("name") not in graph.nodes:
                    results.add(
                        Status.fault("Possible orphan", f"GNS3 node {node.get('name')} is not in the topology.")
                    )
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            results.add(Status.error("GNS3", f"Could not check orphan nodes: {exc}"))
        return results
