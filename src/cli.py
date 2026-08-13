"""
Command line interface for TopologyBuilder.
"""

__license__ = "GNU GPLv3"

import logging
from pathlib import Path
from typing import Optional

import typer

from src.cli_config import load_cli_config
from src.config_file_handler import ConfigFileHandler
from src.connections_handler import (
    APIFunctions,
    ESXiConnection,
    set_esxi_template_api_url,
    set_gns3_template_api_url,
)
from src.factories import Environment
from src.gns3_client import GNS3Client
from src.graph_builder import GraphBuilder
from src.graph_visualizer import print_connection_tree, render_graph
from src.logger_adapter import get_log_file_path, set_console_level
from src.topology_generator_client import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    generate_topology,
)
from src.vm_orchestrator import VMOrchestrator

app = typer.Typer(
    name="TopologyBuilder",
    help="Build and deploy network topologies to GNS3/ESXi from a YAML config file.",
    add_completion=False,
)

_CLI_CONFIG = load_cli_config()

CONFIG_ARG = typer.Argument(
    _CLI_CONFIG.get("config_path"),
    help="Path to the YAML topology config file. Falls back to 'config_path' "
    "in topologybuilder.yml if omitted.",
)

_VERBOSITY_LEVELS = [logging.WARNING, logging.INFO, logging.DEBUG]

ESXI_HOST_OPTION = typer.Option(
    _CLI_CONFIG.get("esxi_host"),
    "--esxi-host",
    envvar="ESXI_HOST",
    help="IPv4 address of the ESXi host.",
)
ESXI_USERNAME_OPTION = typer.Option(
    _CLI_CONFIG.get("esxi_username"),
    "--esxi-username",
    envvar="ESXI_USERNAME",
    help="Username for the ESXi host.",
)
ESXI_PASSWORD_OPTION = typer.Option(
    None,
    "--esxi-password",
    envvar="ESXI_PASSWORD",
    help="Password for the ESXi host. Prompted for if not provided. "
    "Not readable from the config file for security reasons.",
)
ESXI_TEMPLATE_API_URL_OPTION = typer.Option(
    _CLI_CONFIG.get("esxi_template_api_url"),
    "--esxi-template-api-url",
    envvar="ESXI_TEMPLATE_API_URL",
    help="Base URL of the ESXi/NFS template-listing and OVA-download "
    "service. Defaults to this project's own internal network if omitted.",
)
GNS3_TEMPLATE_API_URL_OPTION = typer.Option(
    _CLI_CONFIG.get("gns3_template_api_url"),
    "--gns3-template-api-url",
    envvar="GNS3_TEMPLATE_API_URL",
    help="Base URL of the GNS3 template-listing service. Defaults to this "
    "project's own internal network if omitted.",
)
GNS3_PROJECT_OPTION = typer.Option(
    _CLI_CONFIG.get("gns3_project"),
    "--gns3-project",
    help="Name of the GNS3 project to create or reuse. Defaults to the "
    "config file's name.",
)
GNS3_VM_NAME_OPTION = typer.Option(
    _CLI_CONFIG.get("gns3_vm_name"),
    "--gns3-vm-name",
    help="Name of the GNS3 VM on the ESXi host. Auto-detected if "
    "omitted - matches the one VM whose name contains 'gns3' "
    "(case-insensitive), e.g. 'GNS3' or 'GNS3-VM'.",
)


def _resolve_esxi_credentials(
    esxi_host: Optional[str], esxi_username: Optional[str], esxi_password: Optional[str]
) -> tuple[str, str, str]:
    """
    Validates ESXi credentials gathered from CLI flags/env vars/config file,
    prompting for the password if it wasn't supplied any other way.
    :return: (esxi_host, esxi_username, esxi_password), all guaranteed non-None
    """
    if esxi_host is None:
        raise typer.BadParameter(
            "Missing ESXi host. Pass --esxi-host, set ESXI_HOST, "
            "or add 'esxi_host' to topologybuilder.yml."
        )
    if esxi_username is None:
        raise typer.BadParameter(
            "Missing ESXi username. Pass --esxi-username, set ESXI_USERNAME, "
            "or add 'esxi_username' to topologybuilder.yml."
        )
    if esxi_password is None:
        esxi_password = typer.prompt("ESXi password", hide_input=True)
    return esxi_host, esxi_username, esxi_password


def _resolve_config_path(config_path: Optional[str]) -> str:
    """
    Validates the topology config file path gathered from the CLI argument or
    the config file's own 'config_path' entry.
    :return: config_path, guaranteed non-None
    """
    if config_path is None:
        raise typer.BadParameter(
            "Missing topology config file path. Pass it as an argument, "
            "or add 'config_path' to topologybuilder.yml."
        )
    return config_path


@app.callback()
def main(
    verbose: int = typer.Option(
        0,
        "--verbose",
        "-v",
        count=True,
        help="Increase console log verbosity (-v for INFO, -vv for DEBUG). "
        "The log file always records DEBUG and above.",
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Suppress all console log output except errors."
    ),
    esxi_template_api_url: Optional[str] = ESXI_TEMPLATE_API_URL_OPTION,
    gns3_template_api_url: Optional[str] = GNS3_TEMPLATE_API_URL_OPTION,
) -> None:
    """
    Build and deploy network topologies to GNS3/ESXi from a YAML config file.
    """
    if quiet:
        set_console_level(logging.ERROR)
    else:
        index = min(verbose, len(_VERBOSITY_LEVELS) - 1)
        set_console_level(_VERBOSITY_LEVELS[index])

    if esxi_template_api_url is not None:
        set_esxi_template_api_url(esxi_template_api_url)
    if gns3_template_api_url is not None:
        set_gns3_template_api_url(gns3_template_api_url)


@app.command()
def generate(
    prompt: str = typer.Argument(
        ..., help="Natural-language description of the desired topology."
    ),
    output: str = typer.Option(
        _CLI_CONFIG.get("output", "./config_file_example.yml"),
        "--output",
        "-o",
        help="Path to write the generated config file to.",
    ),
    generator_url: str = typer.Option(
        _CLI_CONFIG.get("generator_url", DEFAULT_BASE_URL),
        envvar="TOPOLOGY_GENERATOR_URL",
        help="Base URL of the Topology Generator API.",
    ),
    timeout: int = typer.Option(
        _CLI_CONFIG.get("generator_timeout", DEFAULT_TIMEOUT_SECONDS),
        "--timeout",
        help="Seconds to wait for a response. Should exceed the server's own "
        "request_timeout * max_retries.",
    ),
) -> None:
    """
    Generate a topology config file from a natural-language prompt via the
    Topology Generator API.
    """
    result = generate_topology(prompt, generator_url, timeout)

    for warning in result.get("warnings", []):
        typer.echo(f"Warning: {warning}", err=True)

    if not result.get("valid"):
        typer.echo("Topology generation failed; no config file written.", err=True)
        raise typer.Exit(code=1)

    Path(output).write_text(result["yaml"])
    typer.echo(f"Wrote generated config to {output}")


@app.command()
def validate(config_path: Optional[str] = CONFIG_ARG) -> None:
    """
    Validate a topology config file without building or deploying anything.
    """
    config_path = _resolve_config_path(config_path)
    handler = ConfigFileHandler(config_path)
    handler.validate_file()
    typer.echo(f"{config_path} is valid.")


@app.command()
def build(
    config_path: Optional[str] = CONFIG_ARG,
    graph: bool = typer.Option(
        False,
        "--graph",
        "-g",
        help="Print a visualization of the topology to the terminal.",
    ),
    list_connections: bool = typer.Option(
        False,
        "--list",
        "-l",
        help="Print a tree listing each device and what it's connected to.",
    ),
) -> None:
    """
    Validate a config file and build the in-memory topology graph, printing a summary.
    """
    config_path = _resolve_config_path(config_path)
    handler = ConfigFileHandler(config_path)
    handler.validate_file()
    graph_builder = GraphBuilder(handler.nodes, handler.edges)
    nodes = graph_builder.build()

    typer.echo(f"Built {len(nodes)} node(s):")
    for name in nodes:
        typer.echo(f"  - {name}")

    if graph:
        typer.echo()
        typer.echo(render_graph(nodes))

    if list_connections:
        typer.echo()
        print_connection_tree(nodes)


@app.command()
def deploy(
    config_path: Optional[str] = CONFIG_ARG,
    esxi_host: Optional[str] = ESXI_HOST_OPTION,
    esxi_username: Optional[str] = ESXI_USERNAME_OPTION,
    esxi_password: Optional[str] = ESXI_PASSWORD_OPTION,
    fresh_gns3_vm: bool = typer.Option(
        False,
        "--fresh-gns3-vm",
        help="Replace the existing GNS3 VM with a freshly imported one from "
        "--gns3-ova-path before deploying. The old VM is powered off and "
        "renamed as a timestamped backup, not deleted.",
    ),
    gns3_ova_path: Optional[str] = typer.Option(
        _CLI_CONFIG.get("gns3_ova_path"),
        "--gns3-ova-path",
        help="Local filesystem path to the GNS3 OVA. Required with --fresh-gns3-vm.",
    ),
    gns3_datastore: Optional[str] = typer.Option(
        _CLI_CONFIG.get("gns3_datastore"),
        "--gns3-datastore",
        help="ESXi datastore to place the fresh GNS3 VM on. Required with --fresh-gns3-vm.",
    ),
    gns3_mgmt_network: Optional[str] = typer.Option(
        _CLI_CONFIG.get("gns3_mgmt_network"),
        "--gns3-mgmt-network",
        help="ESXi port group for the fresh GNS3 VM's management NIC (must be "
        "the OVA's first-added network adapter). Required with --fresh-gns3-vm.",
    ),
    gns3_trunk_network: Optional[str] = typer.Option(
        _CLI_CONFIG.get("gns3_trunk_network"),
        "--gns3-trunk-network",
        help="ESXi port group for the GNS3 VM's VLAN trunk NIC (must be the "
        "OVA's second-added network adapter with --fresh-gns3-vm). Required "
        "with --fresh-gns3-vm. If given (with or without --fresh-gns3-vm), "
        "this port group is also set to accept promiscuous mode/MAC "
        "changes/forged transmits, which GNS3's Cloud nodes need to bridge "
        "topology devices through it.",
    ),
    gns3_trunk_interface: Optional[str] = typer.Option(
        _CLI_CONFIG.get("gns3_trunk_interface"),
        "--gns3-trunk-interface",
        help="Name of the GNS3 VM's own guest-OS network interface for its "
        "VLAN trunk NIC (not the ESXi port group - see --gns3-trunk-network "
        "for that). Auto-detected if omitted - excludes the management "
        "interface and known virtual interfaces, and only picks one "
        "automatically if exactly one candidate remains. Not guaranteed to "
        "be 'eth1' on every GNS3 VM build, e.g. after --fresh-gns3-vm "
        "imports a single-NIC OVA and a second NIC gets added on top.",
    ),
    gns3_project: Optional[str] = GNS3_PROJECT_OPTION,
    gns3_vm_name: Optional[str] = GNS3_VM_NAME_OPTION,
    esxi_datastore: Optional[str] = typer.Option(
        _CLI_CONFIG.get("esxi_datastore"),
        "--esxi-datastore",
        help="ESXi datastore to place newly provisioned topology VMs on. "
        "Required if the topology has any ESXi-hosted (role: VM) nodes.",
    ),
    esxi_ova_cache_dir: Optional[str] = typer.Option(
        _CLI_CONFIG.get("esxi_ova_cache_dir"),
        "--esxi-ova-cache-dir",
        help="Directory to stage downloaded node OVAs in before import. "
        "Defaults to the system temp dir, which may not have room for "
        "multi-gigabyte OVAs - point this at a larger volume if needed.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what deploy would do (port groups, VMs, and GNS3 "
        "nodes/links created or deleted) without changing anything.",
    ),
    incremental: bool = typer.Option(
        False,
        "--incremental",
        help="Skip deleting/recreating anything that already exists by "
        "name - only create what's missing, leaving already-running nodes "
        "untouched. Faster for adding to a running topology, but never "
        "removes nodes dropped from the config and won't pick up an "
        "existing node's image changing while its name stays the same - "
        "use a full (non-incremental) deploy or destroy for either of those.",
    ),
) -> None:
    """
    Validate a config file, build the topology, and deploy it to GNS3/ESXi.
    """
    config_path = _resolve_config_path(config_path)
    esxi_host, esxi_username, esxi_password = _resolve_esxi_credentials(
        esxi_host, esxi_username, esxi_password
    )

    if fresh_gns3_vm:
        missing = [
            flag
            for flag, value in (
                ("--gns3-ova-path", gns3_ova_path),
                ("--gns3-datastore", gns3_datastore),
                ("--gns3-mgmt-network", gns3_mgmt_network),
                ("--gns3-trunk-network", gns3_trunk_network),
            )
            if value is None
        ]
        if missing:
            raise typer.BadParameter(
                f"--fresh-gns3-vm also requires: {', '.join(missing)}"
            )

    handler = ConfigFileHandler(config_path)
    handler.validate_file()
    graph_builder = GraphBuilder(handler.nodes, handler.edges)
    nodes = graph_builder.build()

    if esxi_datastore is None and any(
        node.env == Environment.ON_ESXI for node in nodes.values()
    ):
        raise typer.BadParameter(
            "--esxi-datastore is required: this topology has ESXi-hosted (role: VM) nodes."
        )

    orchestrator = VMOrchestrator(esxi_host, esxi_username, esxi_password)

    if dry_run:
        for line in orchestrator.plan_deploy(
            nodes,
            gns3_project or Path(config_path).stem,
            vm_name=gns3_vm_name,
            fresh_gns3_vm=fresh_gns3_vm,
        ):
            typer.echo(line)
        return

    if fresh_gns3_vm:
        orchestrator.deploy_fresh_gns3_vm(
            gns3_ova_path,
            gns3_datastore,
            gns3_mgmt_network,
            gns3_trunk_network,
            vm_name=gns3_vm_name,
        )

    if not incremental:
        orchestrator.delete_stale_esxi_resources(nodes)
    orchestrator.create_gns3_configuration_file(
        nodes,
        vm_name=gns3_vm_name,
        trunk_network_name=gns3_trunk_network,
        trunk_interface=gns3_trunk_interface,
    )
    orchestrator.deploy_esxi_nodes(
        nodes, esxi_datastore, download_dir=esxi_ova_cache_dir, incremental=incremental
    )
    orchestrator.deploy_gns3_topology(
        nodes,
        gns3_project or Path(config_path).stem,
        vm_name=gns3_vm_name,
        incremental=incremental,
    )
    typer.echo("Deployment complete.")


@app.command()
def destroy(
    config_path: Optional[str] = CONFIG_ARG,
    esxi_host: Optional[str] = ESXI_HOST_OPTION,
    esxi_username: Optional[str] = ESXI_USERNAME_OPTION,
    esxi_password: Optional[str] = ESXI_PASSWORD_OPTION,
    gns3_project: Optional[str] = GNS3_PROJECT_OPTION,
    gns3_vm_name: Optional[str] = GNS3_VM_NAME_OPTION,
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what destroy would delete (ESXi VMs/port groups, GNS3 "
        "nodes) without deleting anything.",
    ),
) -> None:
    """
    Tear down a previously deployed topology: deletes its GNS3 nodes/links
    and its ESXi-hosted VMs/port groups. The only prior way to do this was
    to redeploy over it or use the GNS3 Web UI by hand.
    """
    config_path = _resolve_config_path(config_path)
    esxi_host, esxi_username, esxi_password = _resolve_esxi_credentials(
        esxi_host, esxi_username, esxi_password
    )

    handler = ConfigFileHandler(config_path)
    handler.validate_file()
    graph_builder = GraphBuilder(handler.nodes, handler.edges)
    nodes = graph_builder.build()

    orchestrator = VMOrchestrator(esxi_host, esxi_username, esxi_password)

    if dry_run:
        for line in orchestrator.plan_destroy(
            nodes, gns3_project or Path(config_path).stem, vm_name=gns3_vm_name
        ):
            typer.echo(line)
        return

    orchestrator.delete_stale_esxi_resources(nodes)
    orchestrator.destroy_gns3_topology(
        gns3_project or Path(config_path).stem, vm_name=gns3_vm_name
    )
    typer.echo("Destroy complete.")


@app.command()
def verify(
    config_path: Optional[str] = CONFIG_ARG,
    esxi_host: Optional[str] = ESXI_HOST_OPTION,
    esxi_username: Optional[str] = ESXI_USERNAME_OPTION,
    esxi_password: Optional[str] = ESXI_PASSWORD_OPTION,
    gns3_project: Optional[str] = GNS3_PROJECT_OPTION,
    gns3_vm_name: Optional[str] = GNS3_VM_NAME_OPTION,
    gns3_trunk_network: Optional[str] = typer.Option(
        _CLI_CONFIG.get("gns3_trunk_network"),
        "--gns3-trunk-network",
        help="ESXi port group expected to carry the GNS3 VM's VLAN trunk "
        "NIC. If given, verify also checks the trunk NIC is actually wired "
        "to it. Skipped if omitted.",
    ),
) -> None:
    """
    Run a structural health check against a deployed topology: confirms
    every GNS3 node is started, every ESXi VM is powered on and reports an
    IP, the trunk NIC is wired correctly, and both sides of a link agree on
    VLAN ID. This is NOT a connectivity/ping test - topologybuilder never
    assigns an IP address to any node, so there is no address to ping.
    """
    config_path = _resolve_config_path(config_path)
    esxi_host, esxi_username, esxi_password = _resolve_esxi_credentials(
        esxi_host, esxi_username, esxi_password
    )

    handler = ConfigFileHandler(config_path)
    handler.validate_file()
    graph_builder = GraphBuilder(handler.nodes, handler.edges)
    nodes = graph_builder.build()

    orchestrator = VMOrchestrator(esxi_host, esxi_username, esxi_password)
    results = orchestrator.verify_topology(
        nodes,
        gns3_project or Path(config_path).stem,
        vm_name=gns3_vm_name,
        trunk_network_name=gns3_trunk_network,
    )

    passed = 0
    for ok, description in results:
        typer.echo(f"{'[OK]  ' if ok else '[FAIL]'} {description}")
        passed += ok

    typer.echo(f"{passed}/{len(results)} checks passed")
    if passed != len(results):
        raise typer.Exit(code=1)


@app.command()
def status(
    esxi_host: Optional[str] = ESXI_HOST_OPTION,
    esxi_username: Optional[str] = ESXI_USERNAME_OPTION,
    esxi_password: Optional[str] = ESXI_PASSWORD_OPTION,
    gns3_vm_name: Optional[str] = GNS3_VM_NAME_OPTION,
) -> None:
    """
    Check connectivity to the ESXi host and GNS3 VM, and list GNS3 projects
    and each one's node count/started count. No config file needed.
    """
    esxi_host, esxi_username, esxi_password = _resolve_esxi_credentials(
        esxi_host, esxi_username, esxi_password
    )

    esxi_connection = ESXiConnection(esxi_host, esxi_username, esxi_password)
    typer.echo(f"ESXi host {esxi_host}: reachable")

    vm = (
        esxi_connection.get_vm(gns3_vm_name)
        if gns3_vm_name is not None
        else esxi_connection.find_gns3_vm()
    )
    if vm is None:
        typer.echo("GNS3 VM: not found", err=True)
        raise typer.Exit(code=1)

    ip_address = esxi_connection.get_vm_ip_address(vm.name)
    if ip_address is None:
        typer.echo(
            f"GNS3 VM '{vm.name}': found, but no IP address reported yet", err=True
        )
        raise typer.Exit(code=1)

    client = GNS3Client(f"http://{ip_address}")
    version = client.get_version()
    typer.echo(
        f"GNS3 VM '{vm.name}' at {ip_address}: reachable "
        f"(GNS3 {version.get('version', '?')})"
    )

    projects = client.list_projects()
    if not projects:
        typer.echo("No GNS3 projects.")
        return

    for project in projects:
        nodes = client.list_nodes(project["project_id"])
        started = sum(1 for node in nodes if node.get("status") == "started")
        typer.echo(
            f"  Project '{project['name']}' ({project.get('status', '?')}): "
            f"{len(nodes)} node(s), {started} started"
        )


@app.command()
def templates() -> None:
    """
    List available ESXi and GNS3 template names - valid values for a
    node's 'image' field in a topology config file.
    """
    esxi_templates = sorted(APIFunctions.get_esxi_template_names())
    gns3_templates = sorted(APIFunctions.get_gns3_template_names())

    typer.echo(f"ESXi templates ({len(esxi_templates)}):")
    for name in esxi_templates:
        typer.echo(f"  - {name}")

    typer.echo(f"GNS3 templates ({len(gns3_templates)}):")
    for name in gns3_templates:
        typer.echo(f"  - {name}")


@app.command()
def portgroups(
    esxi_host: Optional[str] = ESXI_HOST_OPTION,
    esxi_username: Optional[str] = ESXI_USERNAME_OPTION,
    esxi_password: Optional[str] = ESXI_PASSWORD_OPTION,
) -> None:
    """
    List the port groups configured on the ESXi host's vSwitches.
    """
    esxi_host, esxi_username, esxi_password = _resolve_esxi_credentials(
        esxi_host, esxi_username, esxi_password
    )

    esxi_connection = ESXiConnection(esxi_host, esxi_username, esxi_password)
    for portgroup in esxi_connection.list_port_groups():
        typer.echo(
            f"{portgroup['name']} (VLAN {portgroup['vlan_id']}) on {portgroup['vswitch']}"
        )


@app.command()
def logs(
    lines: int = typer.Option(
        50,
        "--lines",
        "-n",
        min=1,
        help="Number of most recent log lines to show.",
    ),
) -> None:
    """
    Show the most recent entries from the log file. The log file always
    records DEBUG and above regardless of console verbosity (-v/-vv/-q).
    """
    log_file_path = get_log_file_path()
    if not log_file_path.exists():
        typer.echo(f"No log file found at {log_file_path}.", err=True)
        raise typer.Exit(code=1)

    with open(log_file_path, "r") as file:
        recent_lines = file.readlines()[-lines:]
    for line in recent_lines:
        typer.echo(line, nl=False)


if __name__ == "__main__":
    app()
