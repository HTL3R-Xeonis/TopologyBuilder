"""Read-only health-check commands."""

import os
from pathlib import Path

import typer

from src.connections import ESXiConnection
from src.doctor.doctor import Doctor, check_generator_api, check_template_apis
from src.doctor.status import Status, StatusList
from src.settings import Settings

from .connect_cli import ADDRESS, DATASTORE, ESXI_PASSWORD, ESXI_USER, GNS3_VM, TRUNK, VSWITCH, apply_esxi_options
from .errors import cli_errors
from .generator import load_graph

doctor_app = typer.Typer(help="Check the ESXi, GNS3 and generator setup.", add_completion=False)


def _connection() -> ESXiConnection:
    """Opens an ESXi connection using configured credentials."""
    return ESXiConnection(Settings.ESXI.IP, Settings.ESXI.PORT, Settings.ESXI.USERNAME, Settings.ESXI.PASSWORD)


def _report(results: StatusList) -> None:
    """Displays check results and exits with failure when problems exist."""
    for result in results:
        typer.echo(f"[{result.status.value}] {result.topic}: {result.message}")
    passed = sum(item.status not in Status.FAILURE_STATES for item in results)
    typer.echo(f"{passed}/{len(results)} checks passed")
    if results.has_failures:
        raise typer.Exit(code=1)


def _get_doctor() -> Doctor:
    """Creates the infrastructure doctor or reports a connection error."""
    try:
        return Doctor(_connection())
    except Exception as exc:
        typer.secho(f"Could not connect to ESXi at {Settings.ESXI.IP}: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


@doctor_app.command()
@cli_errors
def preflight(
    generator_url: str | None = typer.Option(
        None, "--generator-url", help="Optional Topology Generator website API URL."
    ),
    address: str | None = ADDRESS,
    esxi_username: str | None = ESXI_USER,
    esxi_password: str | None = ESXI_PASSWORD,
    gns3_vm_name: str | None = GNS3_VM,
    datastore: str | None = DATASTORE,
    virtual_switch: str | None = VSWITCH,
    trunk_port_group: str | None = TRUNK,
) -> None:
    """Checks deployment prerequisites without altering any resources."""
    apply_esxi_options(address, esxi_username, esxi_password, gns3_vm_name, datastore, virtual_switch, trunk_port_group)
    results = check_template_apis()
    results.extend(check_generator_api(generator_url or os.getenv("TOPOLOGY_GENERATOR_URL")))
    try:
        results.extend(Doctor(_connection()).check_setup())
    except (ConnectionError, TimeoutError, ValueError, RuntimeError, TypeError) as exc:
        results.add(Status.error("ESXi", f"Cannot inspect host {Settings.ESXI.IP}: {exc}"))
    _report(results)


@doctor_app.command()
@cli_errors
def verify(
    graph: bool = typer.Option(False, "--graph", "-g", help="Check deployed topology."),
    setup: bool = typer.Option(False, "--setup", "-s", help="Check ESXi and GNS3 setup."),
    address: str | None = ADDRESS,
    esxi_username: str | None = ESXI_USER,
    esxi_password: str | None = ESXI_PASSWORD,
    gns3_vm_name: str | None = GNS3_VM,
    datastore: str | None = DATASTORE,
    virtual_switch: str | None = VSWITCH,
    trunk_port_group: str | None = TRUNK,
) -> None:
    """Verifies the setup, deployed topology, or both."""
    apply_esxi_options(address, esxi_username, esxi_password, gns3_vm_name, datastore, virtual_switch, trunk_port_group)
    # Without flags, verify both. Explicit flags limit the scope.
    check_setup = setup or not (setup or graph)
    check_graph = graph or not (setup or graph)
    topology = load_graph(Path(Settings.TOPOLOGY_FILE)) if check_graph else None
    doctor = _get_doctor()
    results = StatusList()
    try:
        if check_setup:
            results.extend(doctor.check_setup())

        if check_graph:
            results.extend(doctor.is_graph_deployed(topology))

    except (ConnectionError, TimeoutError, ValueError, RuntimeError, TypeError) as exc:
        results.add(Status.error("Doctor", f"Could not finish verification: {exc}"))
    _report(results)


@doctor_app.command()
@cli_errors
def status(
    address: str | None = ADDRESS,
    esxi_username: str | None = ESXI_USER,
    esxi_password: str | None = ESXI_PASSWORD,
    gns3_vm_name: str | None = GNS3_VM,
) -> None:
    """Lists connected services and the state of GNS3 projects."""
    apply_esxi_options(address, esxi_username, esxi_password, gns3_vm_name)
    _report(_get_doctor().status())


@doctor_app.command()
@cli_errors
def portgroups(
    address: str | None = ADDRESS,
    esxi_username: str | None = ESXI_USER,
    esxi_password: str | None = ESXI_PASSWORD,
) -> None:
    """Lists the port groups on the ESXi host."""
    apply_esxi_options(address, esxi_username, esxi_password)
    for name, vlan, switch in _get_doctor().esxi_doctor.list_port_groups():
        typer.echo(f"{name} (VLAN {vlan}) on {switch}")


@doctor_app.command()
@cli_errors
def get(
    port_groups: bool = typer.Option(False, "--port-groups", "-p", help="List ESXi port groups."),
) -> None:
    """Provides the legacy port-group listing command."""
    if not port_groups:
        raise typer.BadParameter("Specify --port-groups, or use 'doctor portgroups'.")
    # The nested 'connect' callback already applies its ESXi settings.
    for name, vlan, switch in _get_doctor().esxi_doctor.list_port_groups():
        typer.echo(f"{name} (VLAN {vlan}) on {switch}")


@doctor_app.command()
@cli_errors
def orphans(
    address: str | None = ADDRESS,
    esxi_username: str | None = ESXI_USER,
    esxi_password: str | None = ESXI_PASSWORD,
) -> None:
    """Lists possible orphaned resources without deleting anything."""
    apply_esxi_options(address, esxi_username, esxi_password)
    graph = load_graph(Path(Settings.TOPOLOGY_FILE))
    _report(_get_doctor().find_orphans(graph))
