import tempfile
from pathlib import Path

import typer

from src.settings import Settings, Verbosity
from src.connections.api_handler import APIHandler
from src.connections.esxi_connection import ESXiConnection
from src.connections.gns3_connection import GNS3Connection
from src.connections.topology_generator_client import TopologyGeneratorClient
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
ESXI_DATASTORE_OPTION = typer.Option(
    None,
    "--datastore",
    help="Datastore to place newly imported topology VMs on. Auto-picks "
    "the one with the most free space if not given.",
)
ESXI_VIRTUAL_SWITCH_OPTION = typer.Option(
    None,
    "--virtual_switch",
    help="Name of the vSwitch to create/remove port groups on. Created "
    "as an internal-only vSwitch if it doesn't already exist.",
)
ESXI_TRUNK_PORT_GROUP_OPTION = typer.Option(
    None,
    "--trunk_port_group",
    help="Port group carrying the GNS3 VM's VLAN trunk NIC. Created if "
    "it doesn't already exist.",
)


def _apply_esxi_options(
    address: str | None,
    esxi_username: str | None,
    esxi_password: str | None,
    gns3_vm_name: str | None,
    datastore: str | None = None,
    virtual_switch: str | None = None,
    trunk_port_group: str | None = None,
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
    if datastore is not None:
        Settings.ESXI.DATASTORE = datastore
    if virtual_switch is not None:
        Settings.ESXI.VIRTUAL_SWITCH = virtual_switch
    if trunk_port_group is not None:
        Settings.ESXI.TRUNK_PORT_GROUP = trunk_port_group


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


def _resolve_project_name(topology_path: Path | str | None = None) -> str:
    """
    Returns the GNS3 project name to use: Settings.GNS3.PROJECT_NAME if
    explicitly set (e.g. via settings.yml's gns3.project_name), otherwise
    the topology file's own stem (e.g. 'my_lab.yaml' -> 'my_lab') - so a
    topology's project is always named after its config file unless a
    fixed name was asked for.
    :param topology_path: path of the topology file to derive the name
        from. Defaults to Settings.TOPOLOGY_FILE - pass the actual output
        path explicitly for a topology just written elsewhere (e.g.
        generate-deploy's --output).
    :return: the resolved project name
    """
    if Settings.GNS3.PROJECT_NAME is not None:
        return Settings.GNS3.PROJECT_NAME
    path = topology_path if topology_path is not None else Settings.TOPOLOGY_FILE
    return Path(path).stem


def _apply_deploy_options(
    only_on_gns3: bool,
    only_on_esxi: bool,
    gns3_username: str | None,
    gns3_password: str | None,
    is_dry_run: bool,
) -> None:
    """
    Applies the given deploy-behaviour options to Settings, shared by
    `deploy` and `generate-deploy`.
    :raises ValueError: if both only_on_gns3 and only_on_esxi are True.
    :return:
    """
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


def _generate_topology(prompt: str, output_path: Path) -> Graph:
    """
    Requests a topology from the Topology Generator API, retrying up to
    Settings.GENERATE_MAX_RETRIES times if a result fails validation.
    Writes the valid result to output_path, prints the resulting graph,
    and returns it. Shared by `generate` and `generate-deploy`.
    :param prompt: natural-language description of the desired topology
    :param output_path: path to write the generated topology file to
    :return: the validated Graph built from the generated topology
    :raises typer.Exit: if no valid topology was generated after all retries
    """
    for attempt in range(1, Settings.GENERATE_MAX_RETRIES + 2):
        result = TopologyGeneratorClient.generate_topology(prompt)

        for warning in result.get("warnings", []):
            typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW, err=True)

        if not result.get("valid"):
            typer.secho(
                f"Attempt {attempt}: topology generation reported invalid, retrying...",
                fg=typer.colors.YELLOW,
                err=True,
            )
            continue

        tmp_path = Path(
            tempfile.mkstemp(
                suffix=".yml",
                prefix="generated_topology_",
                dir=output_path.resolve().parent,
            )[1]
        )
        tmp_path.write_text(result["yaml"])

        try:
            validator = TopologyFileValidation(str(tmp_path))
            validator.validate_file()
        except Exception as exc:
            typer.secho(
                f"Attempt {attempt}: generated topology failed validation "
                f"({type(exc).__name__}: {exc}), retrying...",
                fg=typer.colors.YELLOW,
                err=True,
            )
            tmp_path.unlink(missing_ok=True)
            continue

        tmp_path.replace(output_path)
        typer.secho(f"Wrote generated topology to {output_path}", fg=typer.colors.GREEN)

        graph = Graph(validator.nodes, validator.edges)
        graph.visualize()
        return graph

    typer.secho(
        f"Topology generation failed validation after "
        f"{Settings.GENERATE_MAX_RETRIES} retries; no file written.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=1)


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
    Generates a topology file from a natural-language prompt via the
    Topology Generator API, validates it, and prints the resulting graph.
    Retries generation up to Settings.GENERATE_MAX_RETRIES times if the
    result doesn't validate. Does not deploy the generated topology - see
    `generate-deploy` for that.
    """
    output_path = output if output is not None else Path(Settings.TOPOLOGY_FILE)
    _generate_topology(prompt, output_path)


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
    tree: bool = typer.Option(
        False,
        "--tree",
        help="Prints a colored tree of each device and its exact "
        "interface-to-interface connections, instead of the ASCII diagram.",
    ),
) -> None:
    """Construct the graph and print it."""
    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    if detailed:
        print(repr(graph))
        return

    if tree:
        graph.print_connection_tree()
        return

    graph.visualize()


@app.command()
def deploy(
    address: str = ESXI_ADDRESS_OPTION,
    esxi_username: str = ESXI_USERNAME_OPTION,
    esxi_password: str = ESXI_PASSWORD_OPTION,
    gns3_vm_name: str = GNS3_VM_NAME_OPTION,
    datastore: str = ESXI_DATASTORE_OPTION,
    virtual_switch: str = ESXI_VIRTUAL_SWITCH_OPTION,
    trunk_port_group: str = ESXI_TRUNK_PORT_GROUP_OPTION,
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
    incremental: bool = typer.Option(
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
) -> None:
    """Deploys the nodes from the topology on ESXi and GNS3."""
    _apply_esxi_options(
        address,
        esxi_username,
        esxi_password,
        gns3_vm_name,
        datastore,
        virtual_switch,
        trunk_port_group,
    )

    _apply_deploy_options(
        only_on_gns3, only_on_esxi, gns3_username, gns3_password, is_dry_run
    )
    Settings.GNS3.PROJECT_NAME = _resolve_project_name()

    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    orchestrator = _make_orchestrator()

    orchestrator.deploy_graph(
        graph=graph,
        gns3_username=Settings.GNS3.USERNAME,
        gns3_password=Settings.GNS3.PASSWORD,
        incremental=incremental,
    )
    typer.secho("Deployment complete.", fg=typer.colors.GREEN)


@app.command(name="generate-deploy")
def generate_deploy(
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
    address: str = ESXI_ADDRESS_OPTION,
    esxi_username: str = ESXI_USERNAME_OPTION,
    esxi_password: str = ESXI_PASSWORD_OPTION,
    gns3_vm_name: str = GNS3_VM_NAME_OPTION,
    datastore: str = ESXI_DATASTORE_OPTION,
    virtual_switch: str = ESXI_VIRTUAL_SWITCH_OPTION,
    trunk_port_group: str = ESXI_TRUNK_PORT_GROUP_OPTION,
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
    incremental: bool = typer.Option(
        False,
        "--incremental",
        "-i",
        help="Skip resetting the ESXi vSwitch and recreating the GNS3 "
        "project - only create what's missing by name/endpoint, leaving "
        "already-running VMs/nodes/links untouched.",
    ),
) -> None:
    """
    Generates a topology from a natural-language prompt (see `generate`),
    then immediately deploys it to ESXi/GNS3 (see `deploy`). Generation
    is retried and validated exactly as `generate` does; deployment only
    runs once a valid topology has been generated.
    """
    output_path = output if output is not None else Path(Settings.TOPOLOGY_FILE)
    graph = _generate_topology(prompt, output_path)

    _apply_esxi_options(
        address,
        esxi_username,
        esxi_password,
        gns3_vm_name,
        datastore,
        virtual_switch,
        trunk_port_group,
    )
    _apply_deploy_options(
        only_on_gns3, only_on_esxi, gns3_username, gns3_password, is_dry_run
    )
    Settings.GNS3.PROJECT_NAME = _resolve_project_name(output_path)

    orchestrator = _make_orchestrator()

    orchestrator.deploy_graph(
        graph=graph,
        gns3_username=Settings.GNS3.USERNAME,
        gns3_password=Settings.GNS3.PASSWORD,
        incremental=incremental,
    )
    typer.secho("Deployment complete.", fg=typer.colors.GREEN)


@app.command()
def destroy(
    address: str = ESXI_ADDRESS_OPTION,
    esxi_username: str = ESXI_USERNAME_OPTION,
    esxi_password: str = ESXI_PASSWORD_OPTION,
    gns3_vm_name: str = GNS3_VM_NAME_OPTION,
    datastore: str = ESXI_DATASTORE_OPTION,
    virtual_switch: str = ESXI_VIRTUAL_SWITCH_OPTION,
    trunk_port_group: str = ESXI_TRUNK_PORT_GROUP_OPTION,
) -> None:
    """
    Tears down a previously deployed topology: deletes its GNS3 project's
    nodes and its ESXi-hosted VMs/port groups.
    """
    _apply_esxi_options(
        address,
        esxi_username,
        esxi_password,
        gns3_vm_name,
        datastore,
        virtual_switch,
        trunk_port_group,
    )

    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    orchestrator = _make_orchestrator()
    orchestrator.destroy_graph(graph, _resolve_project_name())
    typer.secho("Destroy complete.", fg=typer.colors.GREEN)


@app.command()
def verify(
    address: str = ESXI_ADDRESS_OPTION,
    esxi_username: str = ESXI_USERNAME_OPTION,
    esxi_password: str = ESXI_PASSWORD_OPTION,
    gns3_vm_name: str = GNS3_VM_NAME_OPTION,
    datastore: str = ESXI_DATASTORE_OPTION,
    virtual_switch: str = ESXI_VIRTUAL_SWITCH_OPTION,
    trunk_port_group: str = ESXI_TRUNK_PORT_GROUP_OPTION,
) -> None:
    """
    Runs a structural health check against a deployed topology: confirms
    every GNS3 node is started, every ESXi VM is powered on and reports an
    IP, the trunk NIC is wired correctly, and both sides of a link agree
    on VLAN ID. This is NOT a connectivity/ping test - this project never
    assigns an IP address to any node from its own config, so there is no
    address to ping.
    """
    _apply_esxi_options(
        address,
        esxi_username,
        esxi_password,
        gns3_vm_name,
        datastore,
        virtual_switch,
        trunk_port_group,
    )

    validator = TopologyFileValidation(Settings.TOPOLOGY_FILE)
    validator.validate_file()

    graph = Graph(validator.nodes, validator.edges)

    orchestrator = _make_orchestrator()
    results = orchestrator.verify_graph(graph, _resolve_project_name())

    passed = 0
    for ok, description in results:
        typer.echo(f"{'[OK]  ' if ok else '[FAIL]'} {description}")
        passed += ok

    typer.echo(f"{passed}/{len(results)} checks passed")
    if passed != len(results):
        raise typer.Exit(code=1)


@app.command()
def doctor(
    address: str = ESXI_ADDRESS_OPTION,
    esxi_username: str = ESXI_USERNAME_OPTION,
    esxi_password: str = ESXI_PASSWORD_OPTION,
    gns3_vm_name: str = GNS3_VM_NAME_OPTION,
    datastore: str = ESXI_DATASTORE_OPTION,
    virtual_switch: str = ESXI_VIRTUAL_SWITCH_OPTION,
    trunk_port_group: str = ESXI_TRUNK_PORT_GROUP_OPTION,
) -> None:
    """
    Read-only preflight check against real infrastructure: reports
    whether the vSwitch/trunk port group exist (or would be auto-created
    by a deploy), which datastore a deploy would use, whether the GNS3 VM
    is reachable, and whether the Template-APIs are reachable. Never
    mutates anything. No topology file needed.
    """
    _apply_esxi_options(
        address,
        esxi_username,
        esxi_password,
        gns3_vm_name,
        datastore,
        virtual_switch,
        trunk_port_group,
    )

    orchestrator = _make_orchestrator()
    results = orchestrator.check_prerequisites()

    passed = 0
    for ok, description in results:
        typer.echo(f"{'[OK]  ' if ok else '[FAIL]'} {description}")
        passed += ok

    typer.echo(f"{passed}/{len(results)} checks passed")
    if passed != len(results):
        raise typer.Exit(code=1)


@app.command()
def status(
    address: str = ESXI_ADDRESS_OPTION,
    esxi_username: str = ESXI_USERNAME_OPTION,
    esxi_password: str = ESXI_PASSWORD_OPTION,
    gns3_vm_name: str = GNS3_VM_NAME_OPTION,
    datastore: str = ESXI_DATASTORE_OPTION,
    virtual_switch: str = ESXI_VIRTUAL_SWITCH_OPTION,
    trunk_port_group: str = ESXI_TRUNK_PORT_GROUP_OPTION,
) -> None:
    """
    Checks connectivity to the ESXi host and GNS3 VM, and lists GNS3
    projects with each one's node/started counts. No topology file needed.
    """
    _apply_esxi_options(
        address,
        esxi_username,
        esxi_password,
        gns3_vm_name,
        datastore,
        virtual_switch,
        trunk_port_group,
    )

    esxi_connection = ESXiConnection(
        Settings.ESXI.IP,
        Settings.ESXI.PORT,
        Settings.ESXI.USERNAME,
        Settings.ESXI.PASSWORD,
    )
    typer.echo(f"ESXi host {Settings.ESXI.IP}: reachable")

    gns3_vm_ip = esxi_connection.get_vm_ip_address(Settings.ESXI.GNS3_VM_NAME)
    if gns3_vm_ip is None:
        typer.secho(
            f"GNS3 VM '{Settings.ESXI.GNS3_VM_NAME}': not found or no IP reported yet",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    version = GNS3Connection.get_version(gns3_vm_ip, Settings.GNS3.PORT)
    typer.echo(
        f"GNS3 VM '{Settings.ESXI.GNS3_VM_NAME}' at {gns3_vm_ip}: reachable "
        f"(GNS3 {version.get('version', '?')})"
    )

    projects = GNS3Connection.list_all_projects(gns3_vm_ip, Settings.GNS3.PORT)
    if not projects:
        typer.echo("No GNS3 projects.")
        return

    for project in projects:
        nodes = GNS3Connection.list_project_nodes(
            gns3_vm_ip, Settings.GNS3.PORT, project["project_id"]
        )
        started = sum(1 for node in nodes if node.get("status") == "started")
        typer.echo(
            f"  Project '{project['name']}' ({project.get('status', '?')}): "
            f"{len(nodes)} node(s), {started} started"
        )


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


@app.command()
def portgroups(
    address: str = ESXI_ADDRESS_OPTION,
    esxi_username: str = ESXI_USERNAME_OPTION,
    esxi_password: str = ESXI_PASSWORD_OPTION,
    datastore: str = ESXI_DATASTORE_OPTION,
    virtual_switch: str = ESXI_VIRTUAL_SWITCH_OPTION,
    trunk_port_group: str = ESXI_TRUNK_PORT_GROUP_OPTION,
) -> None:
    """List the port groups configured on the ESXi host's vSwitch."""
    _apply_esxi_options(
        address,
        esxi_username,
        esxi_password,
        None,
        datastore,
        virtual_switch,
        trunk_port_group,
    )

    esxi_connection = ESXiConnection(
        Settings.ESXI.IP,
        Settings.ESXI.PORT,
        Settings.ESXI.USERNAME,
        Settings.ESXI.PASSWORD,
    )
    for portgroup in esxi_connection.list_port_groups():
        typer.echo(
            f"{portgroup['name']} (VLAN {portgroup['vlan_id']}) on {portgroup['vswitch']}"
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
    for line in recent_lines:
        typer.echo(line, nl=False)
