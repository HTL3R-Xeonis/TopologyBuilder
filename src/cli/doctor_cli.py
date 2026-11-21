"""Read-only health-check commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.connections import ESXiConnection
    from src.doctor.doctor import Doctor

import os
from pathlib import Path

import typer

from src.doctor.status import Status, StatusList
from src.settings import Settings

from .errors import cli_errors
from .generator import load_graph

doctor_app = typer.Typer(help="Check the ESXi, GNS3 and generator setup.", add_completion=False)


def _connection() -> ESXiConnection:
    """Opens an ESXi connection using configured credentials."""
    from src.connections import ESXiConnection

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
    from src.doctor.doctor import Doctor

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
) -> None:
    """Checks deployment prerequisites without altering any resources."""
    from src.doctor.doctor import Doctor, check_generator_api, check_template_apis

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
) -> None:
    """Verifies the setup, deployed topology, or both."""
    check_setup = setup or not graph
    check_graph = graph or not setup
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
def status() -> None:
    """Lists connected services and the state of GNS3 projects."""
    _report(_get_doctor().status())


@doctor_app.command()
@cli_errors
def portgroups() -> None:
    """Lists the port groups on the ESXi host."""
    for name, vlan, switch in _get_doctor().esxi_doctor.list_port_groups():
        typer.echo(f"{name} (VLAN {vlan}) on {switch}")


@doctor_app.command()
@cli_errors
def orphans() -> None:
    """Lists possible orphaned resources without deleting anything."""
    graph = load_graph(Path(Settings.TOPOLOGY_FILE))
    _report(_get_doctor().find_orphans(graph))
