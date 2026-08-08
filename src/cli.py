"""
Command line interface for TopologyBuilder.
"""

__autor__ = "Leon Eiböck"
__date__ = "08/08/2026"
__license__ = "GNU GPLv3"
__status__ = "In development"

import logging
from pathlib import Path
from typing import Optional

import typer

from src.config_file_handler import ConfigFileHandler
from src.graph_builder import GraphBuilder
from src.logger_adapter import set_console_level
from src.topology_generator_client import DEFAULT_BASE_URL, generate_topology
from src.vm_orchestrator import VMOrchestrator

app = typer.Typer(
    name="TopologyBuilder",
    help="Build and deploy network topologies to GNS3/ESXi from a YAML config file.",
    add_completion=False,
)

CONFIG_ARG = typer.Argument(..., help="Path to the YAML topology config file.")

_VERBOSITY_LEVELS = [logging.WARNING, logging.INFO, logging.DEBUG]


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
        DEFAULT_BASE_URL,
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
def build(config_path: str = CONFIG_ARG) -> None:
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


@app.command()
def deploy(
    config_path: str = CONFIG_ARG,
    esxi_host: str = typer.Option(
        ..., envvar="ESXI_HOST", help="IPv4 address of the ESXi host."
    ),
    esxi_username: str = typer.Option(
        ..., envvar="ESXI_USERNAME", help="Username for the ESXi host."
    ),
    esxi_password: Optional[str] = typer.Option(
        None,
        envvar="ESXI_PASSWORD",
        help="Password for the ESXi host. Prompted for if not provided.",
    ),
) -> None:
    """
    Validate a config file, build the topology, and deploy it to GNS3/ESXi.
    """
    if esxi_password is None:
        esxi_password = typer.prompt("ESXi password", hide_input=True)

    handler = ConfigFileHandler(config_path)
    handler.validate_file()
    graph_builder = GraphBuilder(handler.nodes, handler.edges)
    nodes = graph_builder.build()

    orchestrator = VMOrchestrator(esxi_host, esxi_username, esxi_password)
    orchestrator.create_gns3_configuration_file(nodes)
    typer.echo("Deployment complete.")


if __name__ == "__main__":
    app()
