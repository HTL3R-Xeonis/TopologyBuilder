import typer

from src.connections import ESXiConnection
from src.graph import Graph
from src.settings import Settings
from src.topology_file_validation import TopologyFileValidation

doctor_app = typer.Typer()


@doctor_app.command()
def get(
    get_port_groups: bool = typer.Option(
        False, "--port-groups", "-p", help="List the port groups configured on the ESXi host's vSwitch."
    ),
) -> None:
    """Get various resources."""
    selected_parameters = {
        n for n, v in locals().items() if v
    }  # Must be in the first line, may cause unwanted behaviour if not.
    if len(selected_parameters) != 1:
        raise typer.BadParameter(
            f"Choose exactly one parameter. Current parameters: {selected_parameters if selected_parameters else '{}'}"
        )

    if get_port_groups:
        _get_port_groups()


def _get_port_groups() -> None:
    """
    List the port groups configured on the ESXi host's vSwitch.
    :return:
    """
    esxi_connection = ESXiConnection(
        ip=Settings.ESXI.IP,
        port=Settings.ESXI.PORT,
        username=Settings.ESXI.USERNAME,
        password=Settings.ESXI.PASSWORD,
    )
    virtual_switch = esxi_connection.get_virtual_switch(Settings.ESXI.VIRTUAL_SWITCH)
    if virtual_switch is None:
        typer.echo(f"No virtual switch found on the ESXi host by the name: {Settings.ESXI.VIRTUAL_SWITCH}")
        return

    for port_group in esxi_connection.get_vswitch_port_groups(virtual_switch).values():
        typer.echo(f"{port_group.spec.name} (VLAN {port_group.spec.vlanId}) on {virtual_switch.name}")


@doctor_app.command()
def verify(
    check_graph: bool = typer.Option(
        False,
        "--graph",
        "-g",
        help="Checks if the graph is correctly deployed on ESXi and GNS3. Prints a status message for the state of the graph deployed. The topology_graph_file is the source of truth.",
    ),
) -> None:
    """Verify against various of stuff."""
    selected_parameters = {
        n for n, v in locals().items() if v
    }  # Must be in the first line, may cause unwanted behaviour if not.
    if len(selected_parameters) != 1:
        raise typer.BadParameter(
            f"Choose exactly one parameter. Current parameters: {selected_parameters if selected_parameters else '{}'}"
        )

    if check_graph:
        _verify_graph()


def _verify_graph() -> None:
    """
    Checks if the graph is correctly deployed on ESXi and GNS3. Prints a status message for the state of the graph deployed.
    The topology_graph_file is the source of truth.
    :return:
    """
    from src.doctor.doctor import Doctor

    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    doctor = Doctor(
        ESXiConnection(Settings.ESXI.IP, Settings.ESXI.PORT, Settings.ESXI.USERNAME, Settings.ESXI.PASSWORD)
    )
    for status in doctor.is_graph_deployed(graph):
        print(status)
