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
from src.graph_builder import GraphBuilder
from src.graph_visualizer import print_connection_tree, render_graph
from src.logger_adapter import set_console_level
from src.topology_generator_client import DEFAULT_BASE_URL, generate_topology
from src.vm_orchestrator import VMOrchestrator

app = typer.Typer(
    name="TopologyBuilder",
    help="Build and deploy network topologies to GNS3/ESXi from a YAML config file.",
    add_completion=False,
)

CONFIG_ARG = typer.Argument(..., help="Path to the YAML topology config file.")

_CLI_CONFIG = load_cli_config()

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
        "./config_file_example.yml",
        "--output",
        "-o",
        help="Path to write the generated config file to.",
    ),
    generator_url: str = typer.Option(
        _CLI_CONFIG.get("generator_url", DEFAULT_BASE_URL),
        envvar="TOPOLOGY_GENERATOR_URL",
        help="Base URL of the Topology Generator API.",
    ),
) -> None:
    """
    Generate a topology config file from a natural-language prompt via the
    Topology Generator API.
    """
    result = generate_topology(prompt, generator_url)

    for warning in result.get("warnings", []):
        typer.echo(f"Warning: {warning}", err=True)

    if not result.get("valid"):
        typer.echo("Topology generation failed; no config file written.", err=True)
        raise typer.Exit(code=1)

    Path(output).write_text(result["yaml"])
    typer.echo(f"Wrote generated config to {output}")


@app.command()
def validate(config_path: str = CONFIG_ARG) -> None:
    """
    Validate a topology config file without building or deploying anything.
    """
    handler = ConfigFileHandler(config_path)
    handler.validate_file()
    typer.echo(f"{config_path} is valid.")


@app.command()
def build(
    config_path: str = CONFIG_ARG,
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
    config_path: str = CONFIG_ARG,
    esxi_host: Optional[str] = ESXI_HOST_OPTION,
    esxi_username: Optional[str] = ESXI_USERNAME_OPTION,
    esxi_password: Optional[str] = ESXI_PASSWORD_OPTION,
) -> None:
    """
    Validate a config file, build the topology, and deploy it to GNS3/ESXi.
    """
    esxi_host, esxi_username, esxi_password = _resolve_esxi_credentials(
        esxi_host, esxi_username, esxi_password
    )

    handler = ConfigFileHandler(config_path)
    handler.validate_file()
    graph_builder = GraphBuilder(handler.nodes, handler.edges)
    nodes = graph_builder.build()

    orchestrator = VMOrchestrator(esxi_host, esxi_username, esxi_password)
    orchestrator.create_gns3_configuration_file(nodes)
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
