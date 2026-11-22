"""TopologyBuilder command-line interface."""

from pathlib import Path

import typer

from src.settings import Settings, Verbosity
from src.settings.logging_config import configure_logging

from .connect_cli import cleanup, deploy, destroy
from .doctor_cli import doctor_app
from .errors import cli_errors
from .generator import generate_topology, load_graph

app = typer.Typer(name="TopologyBuilder", help="Generate, validate, deploy and check network topologies.")
app.add_typer(doctor_app, name="doctor", help="Read-only health checks.")

# Flat commands matching the dev branch; nested commands remain available.
app.command("deploy")(deploy)
app.command("destroy")(destroy)
app.command("cleanup")(cleanup)


def apply_esxi_options(
    address: str | None = None,
    esxi_username: str | None = None,
    esxi_password: str | None = None,
    gns3_vm_name: str | None = None,
    datastore: str | None = None,
    virtual_switch: str | None = None,
    trunk_port_group: str | None = None,
) -> None:
    """Applies provided ESXi connection and deployment settings."""
    for value, key in (
        (address, "IP"),
        (esxi_username, "USERNAME"),
        (esxi_password, "PASSWORD"),
        (gns3_vm_name, "GNS3_VM_NAME"),
        (datastore, "DATASTORE"),
        (virtual_switch, "VIRTUAL_SWITCH"),
        (trunk_port_group, "TRUNK_PORT_GROUP"),
    ):
        if value is not None:
            setattr(Settings.ESXI, key, value)


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
        "-l",
        help="Use configured template names without API calls.",
    ),
    address: str | None = typer.Option(None, "--address", "-a", help="ESXi host IP address."),
    esxi_username: str | None = typer.Option(None, "--esxi-username", help="ESXi username."),
    esxi_password: str | None = typer.Option(None, "--esxi-password", help="ESXi password.", hide_input=True),
    gns3_vm_name: str | None = typer.Option(None, "--gns3-vm-name", help="GNS3 VM name."),
    datastore: str | None = typer.Option(None, "--datastore", help="ESXi datastore."),
    virtual_switch: str | None = typer.Option(None, "--virtual-switch", help="ESXi internal vSwitch."),
    trunk_port_group: str | None = typer.Option(None, "--trunk-port-group", help="GNS3 VLAN trunk port group."),
    gns3_username: str | None = typer.Option(None, "--gns3-username", "-u", help="GNS3 SSH username."),
    gns3_password: str | None = typer.Option(None, "--gns3-password", "-p", help="GNS3 SSH password.", hide_input=True),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-d", help="Preview deploy, destroy or cleanup without changing resources."
    ),
) -> None:
    """Loads project settings and applies shared CLI overrides."""
    import os

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
    configure_logging()
    if topology is not None:
        Settings.TOPOLOGY_FILE = str(topology)
    if literal_api_values:
        Settings.API.LITERAL_API_VALUES = True

    apply_esxi_options(
        address=address,
        esxi_username=esxi_username,
        esxi_password=esxi_password,
        gns3_vm_name=gns3_vm_name,
        datastore=datastore,
        virtual_switch=virtual_switch,
        trunk_port_group=trunk_port_group,
    )
    if gns3_username is not None:
        Settings.GNS3.USERNAME = gns3_username
    if gns3_password is not None:
        Settings.GNS3.PASSWORD = gns3_password
    if dry_run:
        Settings.IS_DRY_RUN = True


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
    interfaces: bool = typer.Option(False, "--interfaces", help="Show interface labels beside links in the diagram."),
    interactive: bool = typer.Option(
        True, "--interactive/--no-interactive", help="Navigate oversized diagrams in the terminal."
    ),
) -> None:
    """Displays the structure-aware topology in the terminal."""
    graph = load_graph(Path(Settings.TOPOLOGY_FILE))
    if detailed:
        typer.echo(repr(graph))
    else:
        graph.visualize(show_interfaces=interfaces, interactive=interactive)


def _read_prompt(prompt: str | None, prompt_file: Path | None) -> str:
    """
    Returns a topology prompt from an argument or a text file.
    :param prompt: Direct natural-language description.
    :param prompt_file: File containing a natural-language description.
    :return: The topology prompt.
    :raises typer.BadParameter: If the prompt is missing or invalid.
    """
    if (prompt is None) == (prompt_file is None):
        raise typer.BadParameter("Provide either a prompt or --prompt-file.")
    if prompt_file is not None:
        try:
            prompt = prompt_file.expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise typer.BadParameter(f"Cannot read prompt file: {prompt_file}") from exc
    if not prompt or not prompt.strip():
        raise typer.BadParameter("The topology description must not be empty.")
    return prompt.strip()


def _show_generated_topology_summary(graph) -> None:
    """
    Displays the device types and images used in a generated topology.
    :param graph: Generated topology graph.
    """
    from collections import Counter

    roles = Counter(node.role for node in graph.nodes.values())
    images = Counter(node.image for node in graph.nodes.values())

    typer.echo("\nTopology summary:")
    typer.echo(f"  Devices ({len(graph.nodes)}):")
    for role, count in sorted(roles.items(), key=lambda item: (-item[1], item[0])):
        typer.echo(f"    {role}: {count}")

    typer.echo(f"  Images ({len(images)}):")
    for image, count in sorted(images.items(), key=lambda item: (-item[1], item[0])):
        typer.echo(f"    {image}: {count} {'device' if count == 1 else 'devices'}")


@app.command()
@cli_errors
def generate(
    prompt: str | None = typer.Argument(None, help="Natural-language topology description."),
    prompt_file: Path | None = typer.Option(None, "--prompt-file", help="Read the prompt from a text file."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Generated YAML file path."),
    generator_url: str | None = typer.Option(None, "--generator-url", help="Generator API URL."),
) -> None:
    """Generates, validates, and displays a topology from the generator AI."""
    description = _read_prompt(prompt, prompt_file)
    graph = generate_topology(description, output or Path(Settings.TOPOLOGY_FILE), generator_url)
    graph.visualize()
    _show_generated_topology_summary(graph)


@app.command()
@cli_errors
def templates() -> None:
    """Lists template images offered by ESXi and GNS3."""
    from src.connections.api_handler import APIHandler

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
    errors: bool = typer.Option(False, "--errors", "-e", help="Show only warnings and errors."),
) -> None:
    """Displays recent application or warning/error log entries."""
    from collections import deque

    log_path = Path(Settings.ERROR_LOG_FILE_PATH if errors else Settings.LOG_FILE_PATH)
    if not log_path.is_file():
        typer.secho(f"No log file found at {log_path}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    with log_path.open(encoding="utf-8", errors="replace") as stream:
        for line in deque(stream, maxlen=lines):
            typer.echo(line, nl=False)
