from pathlib import Path

import typer

from src.connections.api_handler import APIHandler
from src.graph import Graph
from src.settings import Settings, Verbosity
from src.topology_file_validation import TopologyFileValidation

from .connect_cli import connection_app
from .doctor_cli import doctor_app

app = typer.Typer(
    name="TopologyBuilder",
    help="Build and deploy network topologies to GNS3/ESXi from a YAML config file.",
    add_completion=False,
)

app.add_typer(
    connection_app,
    name="connect",
    help="Connects to the ESXi server for further options and commands.",
)

connection_app.add_typer(
    doctor_app,
    name="doctor",
    help="Path to a few health-check commands against ESXi or GNS3 resources",
)


@app.callback()
def main(
    verbosity: Verbosity = typer.Option(
        None,
        "--verbosity",
        "-v",
        help="Sets the consol verbosity level. Modes: q=Quiet, n=Normal, v=Verbos, d=Debug",
    ),
    settings: Path = typer.Option(
        None,
        "--settings",
        "-s",
        help="Path to a YAML file containing program settings. If not set, default settings will be used.",
    ),
    topology: Path = typer.Option(
        None,
        "--topology",
        "-t",
        help="Path to a YAML file containing topology. If not set, example topology will be used.",
    ),
    literal_api_values: bool = typer.Option(
        False,
        "--literal_api_values",
        "-l",
        help="Use literal api values defined in the settings. If not set API requests will be made.",
    ),
) -> None:
    Settings.initialise_settings_file(custom_settings=settings)
    if verbosity is not None:
        Settings.VERBOSITY_LEVEL = verbosity
    if topology is not None:
        Settings.TOPOLOGY_FILE = str(topology)
    if literal_api_values:
        Settings.API.LITERAL_API_VALUES = literal_api_values


@app.command()
def validate() -> None:
    """Validate the topology file."""
    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()
    typer.secho("Valid.", fg=typer.colors.GREEN)


@app.command()
def visualize(
    detailed: bool = typer.Option(False, "--detail", "-d", help="Prints the details of the network graph."),
) -> None:
    """Construct the graph and print it."""
    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    if detailed:
        print(repr(graph))
        return

    graph.visualize()


@app.command()
def generate(
    prompt: str = typer.Argument(..., help="Natural-language description of the desired topology."),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Path to write the generated topology file to. Defaults to --topology/-t's current value.",
    ),
) -> None:
    """
    Generates a topology file from a natural-language prompt and validates it
    and prints the resulting graph.
    Retries generation up to ``Settings.LLM.MAX_RETRIES`` times if the
    result doesn't validate. Does not deploy the generated topology - see
    `generate-deploy` for that.
    """
    output_path = output if output is not None else Path(Settings.TOPOLOGY_FILE)
    print(output_path, prompt)
    # _generate_topology(prompt, output_path)


@app.command()
def templates() -> None:
    """
    List available ESXi and GNS3 template names - valid values for a
    node's 'image' field in the topology file.
    """
    esxi_templates = sorted(APIHandler.get_esxi_template_names())
    gns3_templates = sorted(APIHandler.get_gns3_template_names())

    typer.echo(f"ESXi templates ({len(esxi_templates)}):")
    for name in esxi_templates:
        typer.echo(f"  - {name}")

    typer.echo(f"GNS3 templates ({len(gns3_templates)}):")
    for name in gns3_templates:
        typer.echo(f"  - {name}")


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
    """Show the most recent entries from the log file."""
    log_file_path = Path(Settings.LOG_FILE_PATH)
    if not log_file_path.exists():
        typer.secho(f"No log file found at {log_file_path}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    with open(log_file_path, "r") as file:
        recent_lines = file.readlines()[-lines:]
    typer.echo("LOGS: ")
    for line in recent_lines:
        typer.echo(line, nl=False)
