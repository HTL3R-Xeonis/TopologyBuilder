import requests

from src.settings import Settings

from .esxi_doctor import ESXiDoctor
from .gns3_doctor import GNS3Doctor
from .status import Status, StatusList


class Doctor:
    """Combines read-only ESXi, GNS3 and API health checks."""

    def __init__(self, esxi_connection) -> None:
        """Uses an established ESXi connection."""
        self.esxi_doctor = ESXiDoctor(esxi_connection)
        self.connection = esxi_connection

    def _gns3_doctor(self) -> tuple[GNS3Doctor | None, StatusList]:
        """Finds the running GNS3 server using its ESXi VM."""
        results = StatusList()
        try:
            ip = self.connection.get_vm_ip_address(Settings.ESXI.GNS3_VM_NAME)
        except (AttributeError, TypeError, ValueError) as exc:
            results.add(Status.error("GNS3", f"GNS3 VM address unavailable: {exc}"))
            return None, results
        if not ip:
            results.add(Status.missing("GNS3", f"No IP address for VM {Settings.ESXI.GNS3_VM_NAME}."))
            return None, results
        results.add(Status.info("GNS3", f"GNS3 VM address: {ip}."))
        return GNS3Doctor(ip, Settings.GNS3.PORT), results

    def check_setup(self) -> StatusList:
        """Checks ESXi and GNS3 deployment prerequisites."""
        results = self.esxi_doctor.check_esxi_setup()
        gns3, lookup = self._gns3_doctor()
        results.extend(lookup)
        if gns3:
            results.extend(gns3.check_setup())
        return results

    def is_graph_deployed(self, graph) -> StatusList:
        """Checks that ESXi and GNS3 contain the expected topology."""
        results = self.esxi_doctor.is_graph_esxi_sided_deployed(graph)
        gns3, lookup = self._gns3_doctor()
        results.extend(lookup)
        if gns3:
            results.extend(gns3.verify_graph(graph))
        return results

    def status(self) -> StatusList:
        """Reports ESXi connectivity and running GNS3 projects."""
        results = StatusList()
        results.add(Status.ok("ESXi", f"Host {Settings.ESXI.IP} connected."))
        gns3, lookup = self._gns3_doctor()
        results.extend(lookup)
        if gns3:
            project_results, _ = gns3.project_status()
            results.extend(project_results)
        return results

    def find_orphans(self, graph) -> StatusList:
        """Reports possible ESXi and GNS3 resources not in the topology."""
        results = self.esxi_doctor.find_orphans(graph)
        gns3, lookup = self._gns3_doctor()
        results.extend(lookup)
        if gns3:
            results.extend(gns3.find_orphans(graph))
        if not results.has_failures:
            results.add(Status.ok("Orphans", "No unexpected lab resources found."))
        return results


def check_template_apis() -> StatusList:
    """Checks availability of the ESXi and GNS3 template websites."""
    results = StatusList()
    if Settings.API.LITERAL_API_VALUES:
        results.add(Status.info("Template API", "Literal template data enabled; remote APIs not checked."))
        return results
    for label, url in (
        ("ESXi", Settings.API.ESXI_TEMPLATE_SERVER_URL),
        ("GNS3", Settings.API.GNS3_TEMPLATE_SERVER_URL),
    ):
        try:
            response = requests.get(f"{url.rstrip('/')}/api/templates", timeout=5)
            response.raise_for_status()
            data = response.json()
            if "templates" not in data:
                raise ValueError("No 'templates' field returned")
            results.add(Status.ok("Template API", f"{label} templates are reachable ({len(data['templates'])})."))
        except (requests.RequestException, ValueError, TypeError) as exc:
            results.add(Status.error("Template API", f"{label} template API at {url} failed: {exc}"))
    return results


def check_generator_api(url: str | None) -> StatusList:
    """Checks whether the topology-generator website exposes its API."""
    results = StatusList()
    if not url:
        results.add(Status.info("Generator API", "No generator URL configured."))
        return results
    if not url.startswith(("http://", "https://")):
        results.add(Status.error("Generator API", "Generator URL must use HTTP or HTTPS."))
        return results
    endpoint = f"{url.rstrip('/')}/api/generate-topology"
    try:
        response = requests.get(endpoint, timeout=5)
        if response.status_code in (200, 405):
            results.add(Status.ok("Generator API", f"Generator endpoint reachable at {endpoint}."))
        else:
            results.add(
                Status.fault("Generator API", f"Generator endpoint returned HTTP {response.status_code}: {endpoint}.")
            )
    except requests.RequestException as exc:
        results.add(Status.error("Generator API", f"Generator website is not reachable: {exc}"))
    return results
