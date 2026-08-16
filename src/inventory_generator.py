"""
Turns a built topology graph plus live GNS3/ESXi state into an Ansible
inventory. Purely a data-shaping module - no network I/O of its own, so it's
easy to unit test in isolation. See vm_orchestrator.py's generate_inventory
for the caller that gathers the live state this module needs.
"""

__license__ = "GNU GPLv3"

from src.factories import Environment, GenericNode

_GNS3_VM_SSH_USERNAME = "gns3"
_GNS3_VM_SSH_PASSWORD = "gns3"


def _addresses_var(node: GenericNode) -> dict[str, str]:
    """
    Collects every addressed interface of a node into a plain
    {interface_name: ip} dict, for use as an informational 'addresses' host
    var - no connection plugin here consumes it directly, it's there for the
    user's own playbook templating.
    :param node: the node to collect addressed interfaces from
    :return: dict of interface name to IP, empty if none are addressed
    """
    return {
        name: interface.ip
        for name, interface in node.interfaces.items()
        if interface.ip is not None
    }


def generate_ansible_inventory(
    nodes: dict[str, GenericNode],
    gns3_ip_address: str | None,
    gns3_nodes_by_name: dict[str, dict],
    esxi_host: str,
    esxi_username: str,
    vm_uuids_by_name: dict[str, str],
) -> dict:
    """
    Builds an ansible-inventory-compatible dict with three groups, one per
    transport this project supports (see HANDOFF.md's Ansible expansion
    scoping): esxi_vms (community.vmware.vmware_tools), gns3_devices
    (ansible.netcommon.telnet against the node's console port), and
    docker_nodes (plain SSH to the GNS3 VM). The caller writes/prints the
    result as YAML.

    The ESXi vCenter/host password is deliberately never embedded as
    plaintext - it's emitted as a Jinja lookup against the ESXI_PASSWORD
    environment variable instead, so the generated inventory file is safe to
    keep around or share. Guest-OS credentials for the ESXi VMs and each GNS3
    node's actual Docker container name are left as clearly marked
    placeholders, since topologybuilder has no concept of either today.
    :param nodes: built topology of the nodes
    :param gns3_ip_address: the GNS3 VM's current IP, or None if it couldn't
        be resolved - gns3_devices/docker_nodes hosts are skipped if so,
        since neither transport works without it
    :param gns3_nodes_by_name: live GNS3 node dicts (from GNS3Client.list_nodes),
        keyed by node name - used for each node's 'node_type' and 'console' port
    :param esxi_host: IPv4 address of the ESXi host
    :param esxi_username: username for the ESXi host
    :param vm_uuids_by_name: each ESXi-hosted node's vSphere instance UUID
        (from ESXiConnection.get_vm_uuid), keyed by node name
    :return: an ansible-inventory-compatible dict
    """
    esxi_hosts: dict[str, dict] = {}
    gns3_device_hosts: dict[str, dict] = {}
    docker_hosts: dict[str, dict] = {}

    for name, node in nodes.items():
        addresses = _addresses_var(node)

        if node.env == Environment.ON_ESXI:
            host_vars = {
                "ansible_connection": "community.vmware.vmware_tools",
                "ansible_vmware_host": esxi_host,
                "ansible_vmware_user": esxi_username,
                "ansible_vmware_password": "{{ lookup('env', 'ESXI_PASSWORD') }}",
                "ansible_vmware_guest_uuid": vm_uuids_by_name.get(name),
                "ansible_vmware_tools_user": "CHANGE_ME",
                "ansible_vmware_tools_password": "CHANGE_ME",
            }
            if addresses:
                host_vars["addresses"] = addresses
            esxi_hosts[name] = host_vars
            continue

        if node.env != Environment.ON_GNS3 or gns3_ip_address is None:
            continue

        gns3_node = gns3_nodes_by_name.get(name)
        if gns3_node is None:
            continue

        if gns3_node.get("node_type") == "docker":
            host_vars = {
                "ansible_host": gns3_ip_address,
                "ansible_user": _GNS3_VM_SSH_USERNAME,
                "ansible_password": _GNS3_VM_SSH_PASSWORD,
                "container_name": name,
            }
            if addresses:
                host_vars["addresses"] = addresses
            docker_hosts[name] = host_vars
        else:
            host_vars = {
                "ansible_host": gns3_ip_address,
                "ansible_connection": "local",
                "console_port": gns3_node.get("console"),
            }
            if addresses:
                host_vars["addresses"] = addresses
            gns3_device_hosts[name] = host_vars

    return {
        "all": {
            "children": {
                "esxi_vms": {"hosts": esxi_hosts},
                "gns3_devices": {"hosts": gns3_device_hosts},
                "docker_nodes": {"hosts": docker_hosts},
            }
        }
    }
