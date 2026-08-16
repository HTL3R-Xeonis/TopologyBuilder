"""
Tests to validate functionality of inventory_generator.py
"""

__license__ = "GNU GPLv3"

import allure

from src import logger_adapter
from src.factories import NodeFactory
from src.inventory_generator import generate_ansible_inventory

logger_adapter.LoggerAdapter.is_test_run = True


@allure.title("ESXi-Node landet in esxi_vms mit vmware_tools-Connection-Vars")
@allure.description(
    "Überprüft, dass eine ESXi-gehostete Node in die esxi_vms Gruppe "
    "einsortiert wird, mit community.vmware.vmware_tools als Connection und "
    "ihrer UUID gesetzt, und dass das ESXi-Passwort nie als Klartext, "
    "sondern nur als env-lookup auftaucht"
)
@allure.tag("positiv-test", "inventory-generator")
@allure.feature("inventory-generator")
@allure.severity(allure.severity_level.CRITICAL)
def inventory_generator_000() -> None:
    nf = NodeFactory()
    vm = nf.create_node("Ubuntu-Server", "VM", "VM1")
    nodes = {"VM1": vm}

    inventory = generate_ansible_inventory(
        nodes, None, {}, "10.20.20.202", "root", {"VM1": "uuid-vm1"}
    )

    host = inventory["all"]["children"]["esxi_vms"]["hosts"]["VM1"]
    assert host["ansible_connection"] == "community.vmware.vmware_tools"
    assert host["ansible_vmware_host"] == "10.20.20.202"
    assert host["ansible_vmware_user"] == "root"
    assert host["ansible_vmware_guest_uuid"] == "uuid-vm1"
    assert "root" not in str(host["ansible_vmware_password"])
    assert "lookup" in host["ansible_vmware_password"]
    assert inventory["all"]["children"]["gns3_devices"]["hosts"] == {}
    assert inventory["all"]["children"]["docker_nodes"]["hosts"] == {}


@allure.title("GNS3-Node (kein Docker) landet in gns3_devices mit Konsolen-Port")
@allure.description(
    "Überprüft, dass eine GNS3-gehostete Node, deren node_type nicht "
    "'docker' ist, in die gns3_devices Gruppe einsortiert wird, mit der "
    "GNS3-VM-IP als ansible_host, ansible_connection: local, und dem "
    "Konsolen-Port aus dem live GNS3-Node-Dict"
)
@allure.tag("positiv-test", "inventory-generator")
@allure.feature("inventory-generator")
@allure.severity(allure.severity_level.CRITICAL)
def inventory_generator_001() -> None:
    nf = NodeFactory()
    router = nf.create_node("VPCS", "ROUTER", "R1")
    nodes = {"R1": router}
    gns3_nodes_by_name = {"R1": {"name": "R1", "node_type": "qemu", "console": 5001}}

    inventory = generate_ansible_inventory(
        nodes, "10.20.20.231", gns3_nodes_by_name, "10.20.20.202", "root", {}
    )

    host = inventory["all"]["children"]["gns3_devices"]["hosts"]["R1"]
    assert host["ansible_host"] == "10.20.20.231"
    assert host["ansible_connection"] == "local"
    assert host["console_port"] == 5001
    assert inventory["all"]["children"]["esxi_vms"]["hosts"] == {}
    assert inventory["all"]["children"]["docker_nodes"]["hosts"] == {}


@allure.title("GNS3-Docker-Node landet in docker_nodes mit SSH auf die GNS3-VM")
@allure.description(
    "Überprüft, dass eine GNS3-gehostete Node mit node_type 'docker' in die "
    "docker_nodes Gruppe einsortiert wird, mit den Stock-SSH-Zugangsdaten "
    "der GNS3-VM und ihrem eigenen Namen als container_name"
)
@allure.tag("positiv-test", "inventory-generator")
@allure.feature("inventory-generator")
@allure.severity(allure.severity_level.CRITICAL)
def inventory_generator_002() -> None:
    nf = NodeFactory()
    container = nf.create_node("VPCS", "PC", "C1")
    nodes = {"C1": container}
    gns3_nodes_by_name = {"C1": {"name": "C1", "node_type": "docker", "console": 5002}}

    inventory = generate_ansible_inventory(
        nodes, "10.20.20.231", gns3_nodes_by_name, "10.20.20.202", "root", {}
    )

    host = inventory["all"]["children"]["docker_nodes"]["hosts"]["C1"]
    assert host["ansible_host"] == "10.20.20.231"
    assert host["ansible_user"] == "gns3"
    assert host["ansible_password"] == "gns3"
    assert host["container_name"] == "C1"


@allure.title("Adressierte Interfaces werden als 'addresses' Host-Var mitgeliefert")
@allure.description(
    "Überprüft, dass eine Node mit mindestens einem adressierten Interface "
    "eine 'addresses' Host-Var {interface: ip} bekommt, während eine Node "
    "ohne adressierte Interfaces keine solche Var bekommt"
)
@allure.tag("positiv-test", "inventory-generator")
@allure.feature("inventory-generator")
@allure.severity(allure.severity_level.NORMAL)
def inventory_generator_003() -> None:
    nf = NodeFactory()
    vm = nf.create_node("Ubuntu-Server", "VM", "VM1")
    vm.add_interface("ens160").ip = "10.0.0.1/24"
    unaddressed_vm = nf.create_node("Rocky 9.2", "VM", "VM2")
    unaddressed_vm.add_interface("ens160")
    nodes = {"VM1": vm, "VM2": unaddressed_vm}

    inventory = generate_ansible_inventory(nodes, None, {}, "10.20.20.202", "root", {})

    hosts = inventory["all"]["children"]["esxi_vms"]["hosts"]
    assert hosts["VM1"]["addresses"] == {"ens160": "10.0.0.1/24"}
    assert "addresses" not in hosts["VM2"]


@allure.title("GNS3-Node ohne live Node-Dict wird übersprungen")
@allure.description(
    "Überprüft, dass eine GNS3-gehostete Node, die nicht in "
    "gns3_nodes_by_name vorkommt (z.B. noch nicht deployt), in keiner "
    "Gruppe landet, statt mit fehlenden Werten aufzutauchen"
)
@allure.tag("negativ-test", "inventory-generator")
@allure.feature("inventory-generator")
@allure.severity(allure.severity_level.NORMAL)
def inventory_generator_004() -> None:
    nf = NodeFactory()
    router = nf.create_node("VPCS", "ROUTER", "R1")
    nodes = {"R1": router}

    inventory = generate_ansible_inventory(
        nodes, "10.20.20.231", {}, "10.20.20.202", "root", {}
    )

    assert inventory["all"]["children"]["gns3_devices"]["hosts"] == {}
    assert inventory["all"]["children"]["docker_nodes"]["hosts"] == {}
