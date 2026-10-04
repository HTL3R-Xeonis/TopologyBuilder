import typer

from src.graph import Graph
from src.orchestrator.graph_orchestrator import GraphOrchestrator
from src.settings import Settings
from src.topology_file_validation import TopologyFileValidation

connection_app = typer.Typer()


@connection_app.callback()
def connection_main(
    address: str = typer.Option(None, "--address", "-a", help="The IP address of the ESXi server."),
    esxi_username: str = typer.Option(None, "--esxi_username", "-u", help="A username of the ESXi server."),
    esxi_password: str = typer.Option(None, "--esxi_password", "-p", help="The password for the ESXi user."),
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
    gns3_username: str = typer.Option(None, "--gns3_username", "-u", help="A username of the GNS3 server."),
    gns3_password: str = typer.Option(None, "--gns3_password", "-p", help="The password for the GNS3 user."),
    is_dry_run: bool = typer.Option(False, "--dry_run", "-d", help="Prints what would have been deployed."),
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


@connection_app.command()
def generate_deploy(
    prompt: str = typer.Argument(..., help="Natural-language description of the desired topology."),
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


@connection_app.command()
def status() -> None:
    """
    Checks connectivity to the ESXi host and GNS3 VM, and lists GNS3
    projects with each one's node/started counts. No topology file needed.
    """
