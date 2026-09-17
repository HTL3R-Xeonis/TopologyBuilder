from pathlib import Path

import typer

from src.connections.api_handler import APIHandler
from src.connections.esxi_connection import ESXiConnection
from src.graph import Graph
from src.orchestrator.graph_orchestrator import GraphOrchestrator
from src.settings import Settings, Verbosity
from src.topology_file_validation import TopologyFileValidation

app = typer.Typer(
    name="TopologyBuilder",
    help="Build and deploy network topologies to GNS3/ESXi from a YAML config file.",
    add_completion=False,
)
connection_app = typer.Typer()

app.add_typer(
    connection_app,
    name="connect",
    help="Connects to the ESXi server for further options and commands.",
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
    detailed: bool = typer.Option(
        False, "--detail", "-d", help="Prints the details of the network graph."
    ),
) -> None:
    """Construct the graph and print it."""
    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    if detailed:
        print(repr(graph))
        return

    graph.visualize()


@connection_app.callback()
def connection_main(
    address: str = typer.Option(
        None, "--address", "-a", help="The IP address of the ESXi server."
    ),
    esxi_username: str = typer.Option(
        None, "--esxi_username", "-u", help="A username of the ESXi server."
    ),
    esxi_password: str = typer.Option(
        None, "--esxi_password", "-p", help="The password for the ESXi user."
    ),
    gns3_vm_name: str = typer.Option(
        None,
        "--gns3_vm_name",
        "-n",
        help="The name of the GNS3 VM on the ESXi server.",
    ),
):
    if address is not None:
        Settings.ESXI.IP = address
    if esxi_username is not None:
        Settings.ESXI.USERNAME = esxi_username
    if esxi_password is not None:
        Settings.ESXI.PASSWORD = esxi_password
    if gns3_vm_name is not None:
        Settings.ESXI.GNS3_VM_NAME = gns3_vm_name


@connection_app.command()
def deploy(
    gns3_username: str = typer.Option(
        None, "--gns3_username", "-u", help="A username of the GNS3 server."
    ),
    gns3_password: str = typer.Option(
        None, "--gns3_password", "-p", help="The password for the GNS3 user."
    ),
    is_dry_run: bool = typer.Option(
        False, "--dry_run", "-d", help="Prints what would have been deployed."
    ),
    is_incremental: bool = typer.Option(
        False,
        "--incremental",
        "-i",
        help="Skip resetting the ESXi vSwitch and recreating the GNS3 "
        "project - only create what's missing by name/endpoint, leaving "
        "already-running VMs/nodes/links untouched. Never removes nodes "
        "dropped from the topology file, and won't pick up an existing "
        "node's image changing while its name stays the same - use a full "
        "(non-incremental) deploy or destroy for either of those.",
    ),
):
    """Deploys the nodes from the topology on ESXi and GNS3."""
    if gns3_username is not None:
        Settings.GNS3.USERNAME = gns3_username
    if gns3_password is not None:
        Settings.GNS3.PASSWORD = gns3_password
    if is_dry_run:
        Settings.IS_DRY_RUN = is_dry_run
    if is_incremental:
        Settings.IS_INCREMENTAL = is_incremental

    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    orchestrator = GraphOrchestrator(
        esxi_host=Settings.ESXI.IP,
        esxi_port=Settings.ESXI.PORT,
        esxi_username=Settings.ESXI.USERNAME,
        esxi_password=Settings.ESXI.PASSWORD,
    )

    orchestrator.execute_graph_deployment(
        graph=graph,
        gns3_username=Settings.GNS3.USERNAME,
        gns3_password=Settings.GNS3.PASSWORD,
    )
    typer.secho("Deployment complete.", fg=typer.colors.GREEN)


@app.command()
def generate(
    prompt: str = typer.Argument(
        ..., help="Natural-language description of the desired topology."
    ),
    output: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Path to write the generated topology file to. Defaults to "
        "--topology/-t's current value.",
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


@connection_app.command()
def generate_deploy(
    prompt: str = typer.Argument(
        ..., help="Natural-language description of the desired topology."
    ),
) -> None:
    """
    Generates a topology from a natural-language prompt,
    then immediately deploys it to ESXi/GNS3. Only deploys the generated topology if a valid one was generated.
    Tries a number of times to generate it, up to ``Settings.LLM.MAX_RETRIES``-times
    """
    print(prompt)


@connection_app.command()
def destroy() -> None:
    """
    Tears down a previously deployed topology: deletes its GNS3 project's
    nodes and its ESXi-hosted VMs/port groups.
    """


@app.command()
def verify() -> None:
    """
    Runs a structural health check against a deployed topology: confirms
    every GNS3 node is started, every ESXi VM is powered on, the trunk NIC
    is wired correctly, and both sides of a link agree on VLAN ID.
    """


@connection_app.command()
def status() -> None:
    """
    Checks connectivity to the ESXi host and GNS3 VM, and lists GNS3
    projects with each one's node/started counts. No topology file needed.
    """


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


@connection_app.command()
def portgroups() -> None:
    """List the port groups configured on the ESXi host's vSwitch."""
    esxi_connection = ESXiConnection(
        ip=Settings.ESXI.IP,
        port=Settings.ESXI.PORT,
        username=Settings.ESXI.USERNAME,
        password=Settings.ESXI.PASSWORD,
    )
    virtual_switch = esxi_connection.get_virtual_switch(Settings.ESXI.VIRTUAL_SWITCH)
    if virtual_switch is None:
        typer.echo(
            f"No virtual switch found on the ESXi host by the name: {Settings.ESXI.VIRTUAL_SWITCH}"
        )
        return

    for port_group in esxi_connection.get_vswitch_port_groups(virtual_switch).values():
        typer.echo(
            f"{port_group.spec.name} (VLAN {port_group.spec.vlanId}) on {virtual_switch.name}"
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
    """Show the most recent entries from the log file."""
    log_file_path = Path(Settings.LOG_FILE_PATH)
    if not log_file_path.exists():
        typer.secho(
            f"No log file found at {log_file_path}.", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1)

    with open(log_file_path, "r") as file:
        recent_lines = file.readlines()[-lines:]
    typer.echo("LOGS: ")
    for line in recent_lines:
        typer.echo(line, nl=False)
