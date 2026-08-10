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
from src.connections_handler import ESXiConnection
from src.factories import Environment
from src.graph_builder import GraphBuilder
from src.graph_visualizer import print_connection_tree, render_graph
from src.logger_adapter import set_console_level
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
) -> None:
    """
    Build and deploy network topologies to GNS3/ESXi from a YAML config file.
    """
    if quiet:
        set_console_level(logging.ERROR)
    else:
        index = min(verbose, len(_VERBOSITY_LEVELS) - 1)
        set_console_level(_VERBOSITY_LEVELS[index])


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
    gns3_trunk_interface: str = typer.Option(
        _CLI_CONFIG.get("gns3_trunk_interface", "eth1"),
        "--gns3-trunk-interface",
        help="Name of the GNS3 VM's own guest-OS network interface for its "
        "VLAN trunk NIC (not the ESXi port group - see --gns3-trunk-network "
        "for that). Not guaranteed to be 'eth1' on every GNS3 VM build, "
        "e.g. after --fresh-gns3-vm imports a single-NIC OVA and a second "
        "NIC gets added on top. If wrong, the error lists the VM's actual "
        "interfaces.",
    ),
    gns3_project: Optional[str] = typer.Option(
        _CLI_CONFIG.get("gns3_project"),
        "--gns3-project",
        help="Name of the GNS3 project to create or reuse. Defaults to the "
        "config file's name.",
    ),
    gns3_vm_name: Optional[str] = typer.Option(
        _CLI_CONFIG.get("gns3_vm_name"),
        "--gns3-vm-name",
        help="Name of the GNS3 VM on the ESXi host. Auto-detected if "
        "omitted - matches the one VM whose name contains 'gns3' "
        "(case-insensitive), e.g. 'GNS3' or 'GNS3-VM'.",
    ),
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

    if fresh_gns3_vm:
        orchestrator.deploy_fresh_gns3_vm(
            gns3_ova_path,
            gns3_datastore,
            gns3_mgmt_network,
            gns3_trunk_network,
            vm_name=gns3_vm_name,
        )

    orchestrator.delete_stale_esxi_resources(nodes)
    orchestrator.create_gns3_configuration_file(
        nodes,
        vm_name=gns3_vm_name,
        trunk_network_name=gns3_trunk_network,
        trunk_interface=gns3_trunk_interface,
    )
    orchestrator.deploy_esxi_nodes(
        nodes, esxi_datastore, download_dir=esxi_ova_cache_dir
    )
    orchestrator.deploy_gns3_topology(
        nodes, gns3_project or Path(config_path).stem, vm_name=gns3_vm_name
    )
    typer.echo("Deployment complete.")


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


if __name__ == "__main__":
    app()
