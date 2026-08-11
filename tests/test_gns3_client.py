"""
Tests to validate functionality of gns3_client.py
"""

__license__ = "GNU GPLv3"

from unittest.mock import MagicMock, patch

import allure
import pytest

from src import logger_adapter
from src.factories import GenericNode, NodeFactory
from src.gns3_client import GNS3Client, deploy_topology

logger_adapter.LoggerAdapter.is_test_run = True
BASE_URL = "http://gns3.example"


def _response(json_data=None, ok=True, status_code=200, text="", content=True):
    response = MagicMock()
    response.ok = ok
    response.status_code = status_code
    response.url = "http://gns3.example/v2/x"
    response.text = text
    response.content = content
    response.json.return_value = json_data
    return response


@allure.title("Fehlerfreie Antwort wird durchgelassen")
@allure.description(
    "Überprüft, dass _raise_for_status bei einer erfolgreichen Antwort keinen Fehler wirft"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_000() -> None:
    client = GNS3Client(BASE_URL)
    client._raise_for_status(_response(ok=True))


@allure.title("Fehlerhafte Antwort enthält den echten Response-Body")
@allure.description(
    "Überprüft, dass _raise_for_status den tatsächlichen Response-Text in der "
    "Fehlermeldung mitgibt, statt ihn wie raise_for_status() zu verschlucken"
)
@allure.tag("negativ-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_001() -> None:
    import requests

    client = GNS3Client(BASE_URL)
    with pytest.raises(
        requests.HTTPError,
        match=r"422 error for .*: platform is required",
    ):
        client._raise_for_status(
            _response(ok=False, status_code=422, text="platform is required")
        )


@allure.title("Node-Erstellung mit flachem Template (QEMU-Stil)")
@allure.description(
    "Überprüft, dass Felder eines flachen Templates (kein eigener 'properties' Key) "
    "korrekt in properties gesammelt werden, Template-Metadaten ausgeschlossen werden "
    "und leere Strings weggelassen werden"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_002() -> None:
    template = {
        "template_id": "tid-1",
        "template_type": "qemu",
        "name": "Ubuntu",
        "category": "guest",
        "builtin": False,
        "default_name_format": "{name}-{0}",
        "compute_id": "local",
        "usage": "",
        "platform": "x86_64",
        "ram": 512,
        "mac_address": "",
    }
    with patch("src.gns3_client.requests.post") as post:
        post.return_value = _response(
            json_data={"node_id": "n1", "name": "PC1", "ports": []}
        )
        client = GNS3Client(BASE_URL)
        client.create_node("proj-1", template, "PC1", 10, 20)

    body = post.call_args.kwargs["json"]
    assert body["name"] == "PC1"
    assert body["template_id"] == "tid-1"
    assert body["node_type"] == "qemu"
    assert body["compute_id"] == "local"
    assert body["properties"] == {"platform": "x86_64", "ram": 512}
    assert "mac_address" not in body["properties"]
    assert "usage" not in body["properties"]
    assert "template_id" not in body["properties"]


@allure.title("Node-Erstellung mit verschachteltem Template (VPCS-Stil)")
@allure.description(
    "Überprüft, dass ein Template mit eigenem 'properties' Key unverändert "
    "übernommen wird, statt es erneut zu verschachteln"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_003() -> None:
    template = {
        "template_id": "tid-2",
        "template_type": "vpcs",
        "name": "VPCS",
        "compute_id": "local",
        "properties": {"console_type": "telnet"},
    }
    with patch("src.gns3_client.requests.post") as post:
        post.return_value = _response(
            json_data={"node_id": "n2", "name": "PC2", "ports": []}
        )
        client = GNS3Client(BASE_URL)
        client.create_node("proj-1", template, "PC2", 0, 0)

    body = post.call_args.kwargs["json"]
    assert body["properties"] == {"console_type": "telnet"}


@allure.title("Symbol wird bei der Node-Erstellung mitgegeben")
@allure.description(
    "Überprüft, dass das Template-Symbol (Icon) als eigenes Top-Level-Feld an "
    "die Node-Erstellung weitergereicht wird, statt in properties zu landen"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_004() -> None:
    template = {
        "template_id": "tid-3",
        "template_type": "vpcs",
        "name": "VPCS",
        "compute_id": "local",
        "symbol": ":/symbols/vpcs_guest.svg",
        "properties": {},
    }
    with patch("src.gns3_client.requests.post") as post:
        post.return_value = _response(
            json_data={"node_id": "n3", "name": "PC3", "ports": []}
        )
        client = GNS3Client(BASE_URL)
        client.create_node("proj-1", template, "PC3", 0, 0)

    body = post.call_args.kwargs["json"]
    assert body["symbol"] == ":/symbols/vpcs_guest.svg"


@allure.title("Kein Symbol-Feld ohne Template-Symbol")
@allure.description(
    "Überprüft, dass 'symbol' nicht im Node-Body auftaucht, wenn das Template "
    "kein Symbol definiert, damit der Server nicht mit einem leeren Wert überschrieben wird"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_005() -> None:
    template = {
        "template_id": "tid-4",
        "template_type": "vpcs",
        "name": "VPCS",
        "compute_id": "local",
        "properties": {},
    }
    with patch("src.gns3_client.requests.post") as post:
        post.return_value = _response(
            json_data={"node_id": "n4", "name": "PC4", "ports": []}
        )
        client = GNS3Client(BASE_URL)
        client.create_node("proj-1", template, "PC4", 0, 0)

    body = post.call_args.kwargs["json"]
    assert "symbol" not in body


@allure.title("Template-Suche ignoriert Groß-/Kleinschreibung und Leerzeichen")
@allure.description(
    "Überprüft, dass find_template ein Template findet, dessen Name sich vom "
    "gesuchten Image nur durch Groß-/Kleinschreibung oder Leerzeichen unterscheidet"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_006() -> None:
    with patch("src.gns3_client.requests.get") as get:
        get.return_value = _response(
            json_data=[{"template_id": "t1", "name": "Cisco IOSv 15.6(1) T"}]
        )
        client = GNS3Client(BASE_URL)
        template = client.find_template("cisco iosv 15.6(1)t")

    assert template["template_id"] == "t1"


@allure.title("Template-Suche ohne Treffer wirft Fehler")
@allure.description(
    "Überprüft, dass find_template einen ValueError wirft, wenn kein Template "
    "zum gesuchten Image passt"
)
@allure.tag("negativ-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_007() -> None:
    with patch("src.gns3_client.requests.get") as get:
        get.return_value = _response(json_data=[{"template_id": "t1", "name": "VPCS"}])
        client = GNS3Client(BASE_URL)
        with pytest.raises(
            ValueError, match=r"No GNS3 template found for image 'Unknown'"
        ):
            client.find_template("Unknown")


@allure.title("Bestehendes, geöffnetes Projekt wird wiederverwendet")
@allure.description(
    "Überprüft, dass get_or_create_project ein bereits vorhandenes, geöffnetes "
    "Projekt zurückgibt, ohne ein neues zu erstellen oder es erneut zu öffnen"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_008() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.post") as post,
    ):
        get.return_value = _response(
            json_data=[{"project_id": "p1", "name": "Lab", "status": "opened"}]
        )
        client = GNS3Client(BASE_URL)
        project = client.get_or_create_project("Lab")

    assert project["project_id"] == "p1"
    post.assert_not_called()


@allure.title("Geschlossenes Projekt wird beim Wiederverwenden geöffnet")
@allure.description(
    "Überprüft, dass get_or_create_project ein vorhandenes, aber geschlossenes "
    "Projekt vor der Rückgabe öffnet"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_009() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.post") as post,
    ):
        get.return_value = _response(
            json_data=[{"project_id": "p1", "name": "Lab", "status": "closed"}]
        )
        post.return_value = _response(
            json_data={"project_id": "p1", "name": "Lab", "status": "opened"}
        )
        client = GNS3Client(BASE_URL)
        client.get_or_create_project("Lab")

    post.assert_called_once_with(
        f"{BASE_URL}/v2/projects/p1/open", json=None, timeout=30
    )


@allure.title("Neues Projekt wird erstellt, wenn keins passt")
@allure.description(
    "Überprüft, dass get_or_create_project ein neues Projekt anlegt, wenn kein "
    "vorhandenes Projekt dem gesuchten Namen entspricht"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_010() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.post") as post,
    ):
        get.return_value = _response(json_data=[])
        post.return_value = _response(json_data={"project_id": "p2", "name": "New"})
        client = GNS3Client(BASE_URL)
        project = client.get_or_create_project("New")

    assert project["project_id"] == "p2"
    post.assert_called_once_with(
        f"{BASE_URL}/v2/projects", json={"name": "New"}, timeout=30
    )


@allure.title("Alle Nodes eines Projekts werden gelöscht")
@allure.description(
    "Überprüft, dass delete_all_nodes jede vorhandene Node im Projekt löscht, "
    "damit ein erneutes Deployment nicht auf alte Nodes stapelt"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_011() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.delete") as delete,
    ):
        get.return_value = _response(json_data=[{"node_id": "n1"}, {"node_id": "n2"}])
        delete.return_value = _response(ok=True, content=False)
        client = GNS3Client(BASE_URL)
        client.delete_all_nodes("proj-1")

    assert delete.call_count == 2
    delete.assert_any_call(f"{BASE_URL}/v2/projects/proj-1/nodes/n1", timeout=300)
    delete.assert_any_call(f"{BASE_URL}/v2/projects/proj-1/nodes/n2", timeout=300)


@allure.title("Löschen bei leerem Projekt ist ein No-Op")
@allure.description(
    "Überprüft, dass delete_all_nodes keine Löschanfrage sendet, wenn das "
    "Projekt bereits keine Nodes enthält"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_012() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.delete") as delete,
    ):
        get.return_value = _response(json_data=[])
        client = GNS3Client(BASE_URL)
        client.delete_all_nodes("proj-1")

    delete.assert_not_called()


@allure.title("Portsuche: exakter, case-insensitiver Treffer")
@allure.description(
    "Überprüft, dass _find_port einen Port findet, dessen Name sich nur in der "
    "Groß-/Kleinschreibung vom gesuchten Interface-Namen unterscheidet"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_013() -> None:
    node = {"name": "R1", "ports": [{"name": "Gi0/0"}, {"name": "Gi0/1"}]}
    port = GNS3Client._find_port(node, "gi0/0")
    assert port["name"] == "Gi0/0"


@allure.title("Portsuche: Single-Port-Node ignoriert den Namen")
@allure.description(
    "Überprüft, dass _find_port bei einer Node mit genau einem Port diesen Port "
    "zurückgibt, selbst wenn sein Name nicht mit dem gesuchten Interface übereinstimmt "
    "(z.B. VPCS, das immer nur 'Ethernet0' hat)"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_014() -> None:
    node = {"name": "PC1", "ports": [{"name": "Ethernet0"}]}
    port = GNS3Client._find_port(node, "gi0/0")
    assert port["name"] == "Ethernet0"


@allure.title("Portsuche: Fallback über die Portnummer")
@allure.description(
    "Überprüft, dass _find_port bei unterschiedlichen Namenskonventionen "
    "(z.B. 'gi0/2' vs. 'Ethernet2') über die abschließende Zahl einen eindeutigen "
    "Treffer findet"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_015() -> None:
    node = {
        "name": "SW1",
        "ports": [{"name": "Ethernet0"}, {"name": "Ethernet1"}, {"name": "Ethernet2"}],
    }
    port = GNS3Client._find_port(node, "gi0/2")
    assert port["name"] == "Ethernet2"


@allure.title("Portsuche ohne eindeutigen Treffer wirft Fehler")
@allure.description(
    "Überprüft, dass _find_port einen ValueError wirft, wenn weder Name noch "
    "Portnummer einen eindeutigen Port ergeben, statt zu raten"
)
@allure.tag("negativ-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_016() -> None:
    node = {
        "name": "SW1",
        "ports": [{"name": "Ethernet0"}, {"name": "Ethernet1"}],
    }
    with pytest.raises(ValueError, match=r"No port named 'gi0/5' on node 'SW1'"):
        GNS3Client._find_port(node, "gi0/5")


@allure.title("Link-Erstellung löst Ports beidseitig auf")
@allure.description(
    "Überprüft, dass create_link die richtigen adapter_number/port_number Werte "
    "beider Seiten aus den Node-Ports auflöst und im Request-Body verwendet"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_017() -> None:
    node_a = {
        "node_id": "na",
        "name": "PC1",
        "ports": [{"name": "Ethernet0", "adapter_number": 0, "port_number": 0}],
    }
    node_b = {
        "node_id": "nb",
        "name": "SW1",
        "ports": [{"name": "Gi0/0", "adapter_number": 1, "port_number": 2}],
    }
    with patch("src.gns3_client.requests.post") as post:
        post.return_value = _response(json_data={"link_id": "l1"})
        client = GNS3Client(BASE_URL)
        client.create_link("proj-1", node_a, "Ethernet0", node_b, "gi0/0")

    body = post.call_args.kwargs["json"]
    assert body["nodes"] == [
        {"node_id": "na", "adapter_number": 0, "port_number": 0},
        {"node_id": "nb", "adapter_number": 1, "port_number": 2},
    ]


@allure.title("Cloud-Node wird an das richtige Host-Interface gebunden")
@allure.description(
    "Überprüft, dass create_cloud_node ein ports_mapping mit dem angegebenen "
    "Host-Interface auf Port 0 erstellt"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_018() -> None:
    with patch("src.gns3_client.requests.post") as post:
        post.return_value = _response(json_data={"node_id": "c1", "name": "cloud-x"})
        client = GNS3Client(BASE_URL)
        client.create_cloud_node("proj-1", "cloud-x", "PC4_gi0-0", 5, 6)

    body = post.call_args.kwargs["json"]
    assert body["node_type"] == "cloud"
    assert body["properties"]["ports_mapping"] == [
        {
            "name": "eth0",
            "interface": "PC4_gi0-0",
            "port_number": 0,
            "type": "ethernet",
        }
    ]


@allure.title("deploy_topology verlinkt zwei GNS3-Nodes direkt")
@allure.description(
    "Überprüft, dass deploy_topology für eine Edge zwischen zwei GNS3-gehosteten "
    "Nodes bestehende Nodes zuerst löscht, dann beide Nodes erstellt, sie direkt "
    "verlinkt (kein Cloud-Node) und am Ende alle Nodes startet"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_019() -> None:
    nf = NodeFactory()
    pc1: GenericNode = nf.create_node("VPCS", "PC", "PC1")
    pc2: GenericNode = nf.create_node("VPCS", "PC", "PC2")
    NodeFactory.create_edge(
        pc1.add_interface("Ethernet0"), pc2.add_interface("Ethernet0")
    )
    nodes = {"PC1": pc1, "PC2": pc2}

    with patch("src.gns3_client.GNS3Client") as client_cls:
        client = client_cls.return_value
        client.get_or_create_project.return_value = {"project_id": "proj-1"}
        client.find_template.return_value = {
            "template_id": "t1",
            "template_type": "vpcs",
            "properties": {},
        }
        client.create_node.side_effect = [
            {"node_id": "n1", "name": "PC1", "ports": [{"name": "Ethernet0"}]},
            {"node_id": "n2", "name": "PC2", "ports": [{"name": "Ethernet0"}]},
        ]

        deploy_topology(BASE_URL, "Lab", nodes)

    client.delete_all_nodes.assert_called_once_with("proj-1")
    assert client.create_node.call_count == 2
    client.create_cloud_node.assert_not_called()
    client.create_link.assert_called_once()
    link_args = client.create_link.call_args.args
    assert link_args[0] == "proj-1"
    assert link_args[2] == "Ethernet0" and link_args[4] == "Ethernet0"
    client.start_all_nodes.assert_called_once_with("proj-1")


@allure.title("deploy_topology überbrückt ESXi-gehostete Nodes via Cloud-Node")
@allure.description(
    "Überprüft, dass deploy_topology für eine Edge zwischen einer GNS3- und einer "
    "ESXi-gehosteten Node einen Cloud-Node an die passende VLAN-Subinterface bindet "
    "und diesen statt der ESXi-Node direkt verlinkt"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_020() -> None:
    nf = NodeFactory()
    router: GenericNode = nf.create_node("VPCS", "ROUTER", "R1")
    vm: GenericNode = nf.create_node("Ubuntu-Server", "VM", "VM1")
    router_if = router.add_interface("Ethernet0")
    vm_if = vm.add_interface("ens160")
    NodeFactory.create_edge(router_if, vm_if)
    nodes = {"R1": router, "VM1": vm}

    with patch("src.gns3_client.GNS3Client") as client_cls:
        client = client_cls.return_value
        client.get_or_create_project.return_value = {"project_id": "proj-1"}
        client.find_template.return_value = {
            "template_id": "t1",
            "template_type": "vpcs",
            "properties": {},
        }
        client.create_node.return_value = {
            "node_id": "n1",
            "name": "R1",
            "ports": [{"name": "Ethernet0"}],
        }
        client.create_cloud_node.return_value = {"node_id": "c1", "name": "cloud-x"}

        deploy_topology(BASE_URL, "Lab", nodes)

    client.create_node.assert_called_once()
    client.create_cloud_node.assert_called_once()
    cloud_args = client.create_cloud_node.call_args.args
    assert cloud_args[0] == "proj-1"
    assert cloud_args[2] == vm_if.esxi_vlan
    client.create_link.assert_called_once()
    client.start_all_nodes.assert_called_once_with("proj-1")


@allure.title("start_all_nodes startet jede Node einzeln")
@allure.description(
    "Überprüft, dass start_all_nodes jede Node über ihren eigenen "
    "Start-Endpunkt einzeln startet, statt GNS3s Batch-'start all'-Endpunkt "
    "zu verwenden - vermeidet, dass viele QEMU-Nodes gleichzeitig gestartet "
    "werden und den Host überlasten"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_021() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.post") as post,
    ):
        get.return_value = _response(
            json_data=[
                {"node_id": "n1", "name": "PC1"},
                {"node_id": "n2", "name": "PC2"},
            ]
        )
        post.return_value = _response(ok=True, content=False)
        client = GNS3Client(BASE_URL)
        client.start_all_nodes("proj-1")

    assert post.call_count == 2
    post.assert_any_call(
        f"{BASE_URL}/v2/projects/proj-1/nodes/n1/start", json=None, timeout=300
    )
    post.assert_any_call(
        f"{BASE_URL}/v2/projects/proj-1/nodes/n2/start", json=None, timeout=300
    )


@allure.title("start_all_nodes startet verbleibende Nodes trotz einzelnem Fehler")
@allure.description(
    "Überprüft, dass start_all_nodes weiterhin versucht, alle übrigen Nodes "
    "zu starten, wenn eine einzelne Node fehlschlägt, und erst danach einen "
    "RuntimeError wirft, der genau die fehlgeschlagene(n) Node(s) benennt - "
    "statt die gesamte Operation beim ersten Fehler abzubrechen"
)
@allure.tag("negativ-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_022() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.post") as post,
    ):
        get.return_value = _response(
            json_data=[
                {"node_id": "n1", "name": "PC1"},
                {"node_id": "n2", "name": "PC2"},
                {"node_id": "n3", "name": "PC3"},
            ]
        )
        post.side_effect = [
            _response(ok=True, content=False),
            _response(ok=False, status_code=409, text="Timeout error"),
            _response(ok=True, content=False),
        ]
        client = GNS3Client(BASE_URL)
        with pytest.raises(
            RuntimeError, match=r"Failed to start 1/3 node\(s\): \['PC2'\]"
        ):
            client.start_all_nodes("proj-1")

    assert post.call_count == 3


@allure.title("Löschen der übrigen Nodes trotz einzelnem Fehler")
@allure.description(
    "Überprüft, dass delete_all_nodes weiterhin versucht, alle übrigen "
    "Nodes zu löschen, wenn eine einzelne Node fehlschlägt (z.B. Timeout "
    "bei einer noch laufenden QEMU-Node unter Host-Last), statt die ganze "
    "Operation abzubrechen - und keinen Fehler wirft, da das Löschen nur "
    "ein Best-Effort-Cleanup vor dem eigentlichen Deployment ist"
)
@allure.tag("negativ-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_023() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.delete") as delete,
    ):
        get.return_value = _response(
            json_data=[
                {"node_id": "n1", "name": "PC1"},
                {"node_id": "n2", "name": "PC2"},
                {"node_id": "n3", "name": "PC3"},
            ]
        )
        delete.side_effect = [
            _response(ok=True, content=False),
            _response(ok=False, status_code=408, text="Read timed out"),
            _response(ok=True, content=False),
        ]
        client = GNS3Client(BASE_URL)
        client.delete_all_nodes("proj-1")  # must not raise

    assert delete.call_count == 3


@allure.title("start_all_nodes wiederholt Start bei Konsolen-Port-Kollision einmal")
@allure.description(
    "Überprüft, dass start_all_nodes bei einer Portkollision auf der Konsole "
    "(z.B. 'address already in use') nach kurzer Wartezeit einen erneuten "
    "Start-Versuch unternimmt, statt die Node sofort als fehlgeschlagen zu zählen"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_024() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.post") as post,
        patch("src.gns3_client.time.sleep") as sleep,
    ):
        get.return_value = _response(json_data=[{"node_id": "n1", "name": "PC1"}])
        post.side_effect = [
            _response(
                ok=False, status_code=409, text="Console port 5000 is already in use"
            ),
            _response(ok=True, content=False),
        ]
        client = GNS3Client(BASE_URL)
        client.start_all_nodes("proj-1")

    assert post.call_count == 2
    sleep.assert_called_once()


@allure.title(
    "start_all_nodes zählt Node bei wiederholter Portkollision als fehlgeschlagen"
)
@allure.description(
    "Überprüft, dass start_all_nodes eine Node als fehlgeschlagen zählt, wenn "
    "auch der einmalige Wiederholungsversuch nach einer Konsolen-Port-Kollision "
    "erneut fehlschlägt"
)
@allure.tag("negativ-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.CRITICAL)
def gns3_client_025() -> None:
    with (
        patch("src.gns3_client.requests.get") as get,
        patch("src.gns3_client.requests.post") as post,
        patch("src.gns3_client.time.sleep"),
    ):
        get.return_value = _response(json_data=[{"node_id": "n1", "name": "PC1"}])
        post.side_effect = [
            _response(ok=False, status_code=409, text="address already in use"),
            _response(ok=False, status_code=409, text="address already in use"),
        ]
        client = GNS3Client(BASE_URL)
        with pytest.raises(
            RuntimeError, match=r"Failed to start 1/1 node\(s\): \['PC1'\]"
        ):
            client.start_all_nodes("proj-1")

    assert post.call_count == 2


@allure.title("get_version liefert die GNS3-Server-Versionsinfo")
@allure.description(
    "Überprüft, dass get_version das Ergebnis von GET /v2/version unverändert "
    "zurückgibt - dient rein als Erreichbarkeitscheck"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_026() -> None:
    with patch("src.gns3_client.requests.get") as get:
        get.return_value = _response(json_data={"version": "2.2.45", "local": True})
        client = GNS3Client(BASE_URL)
        version = client.get_version()

    assert version == {"version": "2.2.45", "local": True}
    get.assert_called_once_with(f"{BASE_URL}/v2/version", timeout=30)


@allure.title("list_projects liefert alle Projekte")
@allure.description(
    "Überprüft, dass list_projects das Ergebnis von GET /v2/projects unverändert "
    "zurückgibt, unabhängig vom Öffnungsstatus"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_027() -> None:
    with patch("src.gns3_client.requests.get") as get:
        get.return_value = _response(
            json_data=[{"project_id": "p1", "name": "Lab", "status": "closed"}]
        )
        client = GNS3Client(BASE_URL)
        projects = client.list_projects()

    assert projects == [{"project_id": "p1", "name": "Lab", "status": "closed"}]


@allure.title("list_nodes liefert alle Nodes eines Projekts")
@allure.description(
    "Überprüft, dass list_nodes das Ergebnis von GET /v2/projects/{id}/nodes "
    "unverändert zurückgibt"
)
@allure.tag("positiv-test", "gns3_client")
@allure.feature("gns3_client")
@allure.severity(allure.severity_level.NORMAL)
def gns3_client_028() -> None:
    with patch("src.gns3_client.requests.get") as get:
        get.return_value = _response(
            json_data=[{"node_id": "n1", "name": "PC1", "status": "started"}]
        )
        client = GNS3Client(BASE_URL)
        nodes = client.list_nodes("proj-1")

    assert nodes == [{"node_id": "n1", "name": "PC1", "status": "started"}]
    get.assert_called_once_with(f"{BASE_URL}/v2/projects/proj-1/nodes", timeout=30)
