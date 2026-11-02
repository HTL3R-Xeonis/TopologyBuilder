"""Deployment commands and ESXi connection options."""

from pathlib import Path

import typer

from src.settings import Settings

from .errors import cli_errors

connection_app = typer.Typer(help="Deployment and connection commands.", add_completion=False)

ADDRESS = typer.Option(None, "--address", "-a", help="ESXi host IP address.")
ESXI_USER = typer.Option(None, "--esxi-username", "--esxi_username", help="ESXi username.")
ESXI_PASSWORD = typer.Option(None, "--esxi-password", "--esxi_password", help="ESXi password.", hide_input=True)
GNS3_VM = typer.Option(None, "--gns3-vm-name", "--gns3_vm_name", help="GNS3 VM name.")
DATASTORE = typer.Option(None, "--datastore", help="ESXi datastore.")
VSWITCH = typer.Option(None, "--virtual-switch", "--virtual_switch", help="ESXi internal vSwitch.")
TRUNK = typer.Option(None, "--trunk-port-group", "--trunk_port_group", help="GNS3 VLAN trunk port group.")


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


@connection_app.callback()
@cli_errors
def connection_main(
    address: str | None = ADDRESS,
    esxi_username: str | None = ESXI_USER,
    esxi_password: str | None = ESXI_PASSWORD,
    gns3_vm_name: str | None = GNS3_VM,
    datastore: str | None = DATASTORE,
    virtual_switch: str | None = VSWITCH,
    trunk_port_group: str | None = TRUNK,
) -> None:
    """Configures the connection for nested commands."""
    apply_esxi_options(address, esxi_username, esxi_password, gns3_vm_name, datastore, virtual_switch, trunk_port_group)


def deploy_graph(graph, dry_run: bool = False, incremental: bool = False) -> None:
    """Deploys a graph or displays a safe deployment preview."""
    from src.orchestrator.graph_orchestrator import GraphOrchestrator

    if incremental:
        typer.secho("Incremental deployment is not implemented in this project version.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    if dry_run or Settings.IS_DRY_RUN:
        typer.echo(f"DRY RUN: {len(graph.nodes)} node(s) in {Settings.GNS3.PROJECT_NAME}.")
        for node in graph.nodes.values():
            typer.echo(f"  {node.name}: {node.image} ({node.env.name})")
        typer.echo("No ESXi or GNS3 resources changed.")
        return
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
@cli_errors
def deploy(
    address: str | None = ADDRESS,
    esxi_username: str | None = ESXI_USER,
    esxi_password: str | None = ESXI_PASSWORD,
    gns3_vm_name: str | None = GNS3_VM,
    datastore: str | None = DATASTORE,
    virtual_switch: str | None = VSWITCH,
    trunk_port_group: str | None = TRUNK,
    gns3_username: str | None = typer.Option(None, "--gns3-username", "--gns3_username", "-u"),
    gns3_password: str | None = typer.Option(None, "--gns3-password", "--gns3_password", "-p", hide_input=True),
    dry_run: bool = typer.Option(
        False, "--dry-run", "--dry_run", "-d", help="Preview deployment without modifying resources."
    ),
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Unavailable in this project version."),
) -> None:
    """Validates and deploys the configured topology to ESXi and GNS3."""
    from .generator import load_graph

    apply_esxi_options(address, esxi_username, esxi_password, gns3_vm_name, datastore, virtual_switch, trunk_port_group)
    if gns3_username is not None:
        Settings.GNS3.USERNAME = gns3_username
    if gns3_password is not None:
        Settings.GNS3.PASSWORD = gns3_password
    if incremental:
        typer.secho("Incremental deployment is not implemented in this project version.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    graph = load_graph(Path(Settings.TOPOLOGY_FILE))
    deploy_graph(graph, dry_run=dry_run)


@connection_app.command("generate-deploy")
@cli_errors
def generate_deploy(*args, **kwargs) -> None:
    """Generates, validates, and deploys a topology."""
    typer.secho("Unsupported Option. Instead use 'generate' and 'deploy'.")


@connection_app.command()
@cli_errors
def destroy() -> None:
    """Reports that safe topology removal is not supported."""
    typer.secho(
        "Destroy is not implemented in the included orchestrator; nothing was removed.", fg=typer.colors.RED, err=True
    )
    raise typer.Exit(code=2)
