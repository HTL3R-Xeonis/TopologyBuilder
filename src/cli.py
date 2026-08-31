from pathlib import Path

import typer

from src.settings import Settings, Verbosity
from src.graph import Graph
from src.topology_file_validation import TopologyFileValidation
from src.vm_orchestrator.vm_orchestrator import VMOrchestrator


app = typer.Typer(
    name="TopologyBuilder",
    help="Build and deploy network topologies to GNS3/ESXi from a YAML config file.",
    add_completion=False,
)

ESXI_ADDRESS_OPTION = typer.Option(
    None, "--address", "-a", help="The IP address of the ESXi server."
)
ESXI_USERNAME_OPTION = typer.Option(
    None, "--esxi_username", help="A username of the ESXi server."
)
ESXI_PASSWORD_OPTION = typer.Option(
    None, "--esxi_password", help="The password for the ESXi user."
)
GNS3_VM_NAME_OPTION = typer.Option(
    None, "--gns3_vm_name", "-n", help="The name of the GNS3 VM on the ESXi server."
)


def _apply_esxi_options(
    address: str | None,
    esxi_username: str | None,
    esxi_password: str | None,
    gns3_vm_name: str | None,
) -> None:
    """
    Applies the given ESXi/GNS3-VM connection options to Settings, leaving
    any not given at their current value.
    :return:
    """
    if address is not None:
        Settings.ESXI.IP = address
    if esxi_username is not None:
        Settings.ESXI.USERNAME = esxi_username
    if esxi_password is not None:
        Settings.ESXI.PASSWORD = esxi_password
    if gns3_vm_name is not None:
        Settings.ESXI.GNS3_VM_NAME = gns3_vm_name


def _make_orchestrator() -> VMOrchestrator:
    """
    Builds a VMOrchestrator connected according to the current ESXi settings.
    :return:
    """
    return VMOrchestrator(
        esxi_host=Settings.ESXI.IP,
        esxi_port=Settings.ESXI.PORT,
        esxi_username=Settings.ESXI.USERNAME,
        esxi_password=Settings.ESXI.PASSWORD,
        gns3_vm_name=Settings.ESXI.GNS3_VM_NAME,
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
    if settings is not None:
        Settings.initialise_settings(str(settings))
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


@app.command()
def deploy(
    address: str = ESXI_ADDRESS_OPTION,
    esxi_username: str = ESXI_USERNAME_OPTION,
    esxi_password: str = ESXI_PASSWORD_OPTION,
    gns3_vm_name: str = GNS3_VM_NAME_OPTION,
    gns3_username: str = typer.Option(
        None, "--gns3_username", "-u", help="A username of the GNS3 server."
    ),
    gns3_password: str = typer.Option(
        None, "--gns3_password", "-p", help="The password for the GNS3 user."
    ),
    is_dry_run: bool = typer.Option(
        False, "--dry_run", "-d", help="Prints what would have been deployed."
    ),
    only_on_gns3: bool = typer.Option(
        False,
        "--only_on_gns3",
        "-g",
        help="Only deploys nodes which are in the GNS3 environment.",
    ),
    only_on_esxi: bool = typer.Option(
        False,
        "--only_on_esxi",
        "-e",
        help="Only deploys nodes which are in the ESXi environment."
        "Still creates Cloud-nodes on GNS3 to ensure possible connections between the ESXi-VMs.",
    ),
) -> None:
    """Deploys the nodes from the topology on ESXi and GNS3."""
    _apply_esxi_options(address, esxi_username, esxi_password, gns3_vm_name)

    if only_on_gns3:
        Settings.ONLY_ON_GNS3 = only_on_gns3
    if only_on_esxi:
        Settings.ONLY_ON_ESXI = only_on_esxi
    if only_on_gns3 and only_on_esxi:
        raise ValueError(
            "Only deploying in both environments does not make sense, if there are only these two environments."
        )

    if gns3_username is not None:
        Settings.GNS3.USERNAME = gns3_username
    if gns3_password is not None:
        Settings.GNS3.PASSWORD = gns3_password
    if is_dry_run:
        Settings.IS_DRY_RUN = is_dry_run

    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    orchestrator = _make_orchestrator()

    orchestrator.deploy_graph(
        graph=graph,
        gns3_username=Settings.GNS3.USERNAME,
        gns3_password=Settings.GNS3.PASSWORD,
    )


@app.command()
def destroy(
    address: str = ESXI_ADDRESS_OPTION,
    esxi_username: str = ESXI_USERNAME_OPTION,
    esxi_password: str = ESXI_PASSWORD_OPTION,
    gns3_vm_name: str = GNS3_VM_NAME_OPTION,
) -> None:
    """
    Tears down a previously deployed topology: deletes its GNS3 project's
    nodes and its ESXi-hosted VMs/port groups.
    """
    _apply_esxi_options(address, esxi_username, esxi_password, gns3_vm_name)

    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    orchestrator = _make_orchestrator()
    orchestrator.destroy_graph(graph, Settings.GNS3.PROJECT_NAME)
    typer.secho("Destroy complete.", fg=typer.colors.GREEN)
