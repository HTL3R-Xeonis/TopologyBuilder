"""TopologyBuilder command-line interface."""

import os
from collections import deque
from pathlib import Path

import typer

from src.connections.api_handler import APIHandler
from src.settings import Settings, Verbosity

from .connect_cli import deploy, destroy
from .doctor_cli import doctor_app
from .errors import cli_errors
from .generator import generate_topology, load_graph

app = typer.Typer(name="TopologyBuilder", help="Generate, validate, deploy and check network topologies.")
app.add_typer(doctor_app, name="doctor", help="Read-only health checks.")

# Flat commands matching the dev branch; nested commands remain available.
app.command("deploy")(deploy)
app.command("destroy")(destroy)

# app.command("verify")(verify)
# app.command("preflight")(preflight)
# app.command("status")(status)
# app.command("portgroups")(portgroups)
# app.command("orphans")(orphans)


@app.callback()
@cli_errors
def main(
    verbosity: Verbosity | None = typer.Option(
        None, "--verbosity", "-v", help="q=quiet, n=normal, v=verbose, d=debug."
    ),
    settings: Path | None = typer.Option(None, "--settings", "-s", help="Custom YAML settings file."),
    topology: Path | None = typer.Option(None, "--topology", "-t", help="Topology YAML file."),
    literal_api_values: bool = typer.Option(
        False,
        "--literal-api-values",
        "--literal_api_values",
        "-l",
        help="Use configured template names without API calls.",
    ),
) -> None:
    """Loads project settings and command-line overrides."""
    # Reading settings must not request passwords when showing help or validating files.
    missing = [name for name in ("ESXI_PASSWORD", "GNS3_PASSWORD") if name not in os.environ]
    for name in missing:
        os.environ[name] = ""
    try:
        Settings.initialise_settings_file(custom_settings=settings)
    finally:
        for name in missing:
            os.environ.pop(name, None)
    if verbosity is not None:
        Settings.VERBOSITY_LEVEL = verbosity
    if topology is not None:
        Settings.TOPOLOGY_FILE = str(topology)
    if literal_api_values:
        Settings.API.LITERAL_API_VALUES = True


@app.command()
@cli_errors
def validate() -> None:
    """Validates the configured topology YAML."""

    load_graph(Path(Settings.TOPOLOGY_FILE))
    typer.secho("Valid.", fg=typer.colors.GREEN)


@app.command()
@cli_errors
def visualize(
    detailed: bool = typer.Option(False, "--detail", "-d", help="Print graph details."),
) -> None:
    """Displays the topology graph in the terminal."""
    graph = load_graph(Path(Settings.TOPOLOGY_FILE))
    if detailed:
        typer.echo(repr(graph))
    else:
        graph.visualize()


@app.command()
@cli_errors
def generate(
    prompt: str = typer.Argument(..., help="Topology description."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Generated YAML file path."),
    generator_url: str | None = typer.Option(None, "--generator-url", help="Topology Generator website API URL."),
) -> None:
    """Generates and validates YAML through the generator website API."""
    graph = generate_topology(prompt, output or Path(Settings.TOPOLOGY_FILE), generator_url)
    graph.visualize()


@app.command()
@cli_errors
def templates() -> None:
    """Lists template images offered by ESXi and GNS3."""
    for label, names in (
        ("ESXi", APIHandler.get_esxi_template_names()),
        ("GNS3", APIHandler.get_gns3_template_names()),
    ):
        typer.echo(f"{label} templates ({len(names)}):")
        for name in sorted(names):
            typer.echo(f"  - {name}")


@app.command()
@cli_errors
def logs(
    lines: int = typer.Option(50, "--lines", "-n", min=1, help="Number of recent lines."),
) -> None:
    """Displays the most recent application log lines."""
    log_path = Path(Settings.LOG_FILE_PATH)
    if not log_path.is_file():
        typer.secho(f"No log file found at {log_path}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    with log_path.open(encoding="utf-8", errors="replace") as stream:
        for line in deque(stream, maxlen=lines):
            typer.echo(line, nl=False)
