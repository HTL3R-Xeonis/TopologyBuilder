"""Deployment commands and ESXi connection options."""

from pathlib import Path

import typer

from src.settings import Settings

from ..graph import Graph
from .errors import cli_errors

connection_app = typer.Typer(help="Deployment and connection commands.", add_completion=False)


def _get_orchestrator(existing_project_only: bool = False):
    """
    Returns an orchestrator for deployment or read-only inspection.
    :param existing_project_only: Do not create or open GNS3 projects.
    :return: Configured graph orchestrator.
    :raises ConnectionError: If an infrastructure connection fails.
    :raises RuntimeError: If the GNS3 VM cannot be located.
    """
    from src.orchestrator.graph_orchestrator import GraphOrchestrator

    return GraphOrchestrator(
        esxi_host=Settings.ESXI.IP,
        esxi_port=Settings.ESXI.PORT,
        esxi_username=Settings.ESXI.USERNAME,
        esxi_password=Settings.ESXI.PASSWORD,
        gns3_username=Settings.GNS3.USERNAME,
        gns3_password=Settings.GNS3.PASSWORD,
        existing_project_only=existing_project_only,
    )


def _describe_change(kind: str, item, changes) -> str:
    """
    Returns a readable description of a planned topology change.
    :param kind: Resource category.
    :param item: Planned change entry.
    :param changes: Topology change plan.
    :return: Description of the affected resource.
    """
    if kind == "port_group" and isinstance(item, tuple):
        return f"{item[0]} (VLAN {item[1]})"
    if kind == "gns3_link" and isinstance(item, tuple):
        first, second = item
        first_interface = first.get_interface(second)
        second_interface = second.get_interface(first)
        left = first_interface.name if first_interface is not None else "?"
        right = second_interface.name if second_interface is not None else "?"
        return f"{first.name}[{left}] <-> {second.name}[{right}]"
    if kind == "gns3_node":
        if isinstance(item, tuple):
            node, properties = item
            return f"{node.name}: {properties}"
        return f"{item.name} ({item.image})"
    if kind == "esxi_vm":
        return f"{item.name} ({item.image})" if hasattr(item, "image") else item.name
    if kind == "gns3_vm_adapter":
        vm, nic, group = item
        return f"{vm.name}, {nic.deviceInfo.label} -> {group}"
    if kind == "esxi_nic":
        if len(item) == 2:
            vm, groups = item
            return f"{vm.name}: {', '.join(groups)}"
        vm, nic, group = item
        return f"{vm.name}, {nic.deviceInfo.label} -> {group}"
    if kind == "vlans" and changes.gns3_vlan_setup is not None:
        vlan_id = changes.gns3_vlan_setup.vlans.get(item)
        if vlan_id is not None:
            return f"{item} (VLAN {vlan_id})"
    return str(item)


def _show_changes(changes, only_deletions: bool = False) -> None:
    """
    Displays planned resource operations and detected conflicts.
    :param changes: Topology change plan.
    :param only_deletions: Display only removal operations.
    :raises typer.Exit: If the plan contains conflicts.
    """
    labels = {
        "virtual_switch": "ESXi virtual switch(es)",
        "port_group": "ESXi port group(s)",
        "esxi_vm": "ESXi VM(s)",
        "esxi_nic": "ESXi VM adapter(s)",
        "gns3_vm_adapter": "GNS3 host VM adapter(s)",
        "gns3_node": "GNS3 node(s)",
        "gns3_link": "GNS3 link(s)",
        "vlans": "GNS3 VLAN interface(s)",
    }
    pools = (
        [("Delete", changes.to_delete)]
        if only_deletions
        else [
            ("Add", changes.to_add),
            ("Update", changes.to_change),
            ("Delete", changes.to_delete),
        ]
    )
    for action, pool in pools:
        for kind, items in pool.items():
            if not items:
                continue
            typer.echo(f"  {action} {labels.get(kind, kind)} ({len(items)}):")
            for item in items:
                typer.echo(f"    - {_describe_change(kind, item, changes)}")
    if changes.conflicts:
        typer.secho("Conflicts prevent execution:", fg=typer.colors.RED, err=True)
        for conflict in changes.conflicts:
            typer.echo(f"  - {conflict}", err=True)
        raise typer.Exit(code=1)


def deploy_graph(graph: Graph) -> None:
    """
    Deploys a topology or previews its planned changes.
    :param graph: Desired topology.
    :raises typer.Exit: If the change plan contains conflicts.
    :raises RuntimeError: If infrastructure inspection or deployment fails.
    """
    preview = bool(Settings.IS_DRY_RUN)
    orchestrator = _get_orchestrator(existing_project_only=preview)
    changes = orchestrator.plan_topology_deployment(graph)
    if preview:
        mode = "Fresh deployment" if Settings.NEW else "Deployment"
        typer.echo(f"DRY RUN: {mode} plan for {Settings.GNS3.PROJECT_NAME}:")
        project = orchestrator.gns3_orchestrator.gns3_connection.project_gns3_info
        if project is None:
            typer.echo(f"  Add GNS3 project: {Settings.GNS3.PROJECT_NAME}")
        elif project.get("status") == "closed":
            typer.echo(f"  Open GNS3 project: {Settings.GNS3.PROJECT_NAME}")
        _show_changes(changes)
        if not changes.has_changes and project is not None and project.get("status") != "closed":
            typer.echo("  No changes required.")
        typer.echo("No ESXi or GNS3 resources changed.")
        return
    if Settings.NEW:
        typer.secho(
            "Recreating graph-owned VMs and GNS3 nodes; their existing data will be lost.", fg=typer.colors.YELLOW
        )
    orchestrator.apply_topology_changes(changes)
    typer.secho("Deployment complete.", fg=typer.colors.GREEN)


@connection_app.command()
@cli_errors
def deploy(
    new: bool = typer.Option(
        False, "--new", "-n", help="VMs, GNS3 nodes and links which already exist will get replaced by a new one."
    ),
) -> None:
    """Validates and deploys the configured topology or previews its changes."""
    from .generator import load_graph

    if new:
        Settings.NEW = True
    graph = load_graph(Path(Settings.TOPOLOGY_FILE))
    deploy_graph(graph)


@connection_app.command()
@cli_errors
def destroy(
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm deletion without prompting."),
) -> None:
    """Removes resources belonging to the configured topology."""
    from loguru import logger

    from .generator import load_graph

    graph = load_graph(Path(Settings.TOPOLOGY_FILE))
    orchestrator = _get_orchestrator(existing_project_only=True)
    changes = orchestrator.plan_topology_destruction(graph)
    typer.echo("Topology destruction plan:")
    _show_changes(changes, only_deletions=True)
    if not changes.has_changes:
        typer.echo("No graph-owned resources found; nothing to delete.")
        return
    if Settings.IS_DRY_RUN:
        typer.echo("DRY RUN: No ESXi or GNS3 resources changed.")
        return
    if not yes and not typer.confirm("Permanently delete these topology resources?", default=False):
        logger.info("Topology destruction cancelled")
        raise typer.Abort()
    orchestrator.apply_topology_destruction(changes)
    typer.secho("Topology resources removed.", fg=typer.colors.GREEN)
