from pathlib import Path

import typer

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
    Settings.initialise_settings(custom_settings=settings)
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
):
    """Deploys the nodes from the topology on ESXi and GNS3."""
    if gns3_username is not None:
        Settings.GNS3.USERNAME = gns3_username
    if gns3_password is not None:
        Settings.GNS3.PASSWORD = gns3_password
    if is_dry_run:
        Settings.IS_DRY_RUN = is_dry_run

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
