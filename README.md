# TopologyBuilder

Build and deploy network topologies to GNS3 and ESXi from a YAML topology
file. Nodes in the topology file can be either GNS3-simulated devices
(routers, switches, PCs) or full VMs deployed directly onto an ESXi host;
the two are bridged together at the network layer so the whole topology
behaves as one connected lab.

## How to Download

```bash
git clone https://github.com/HTL3R-Xeonis/TopologyBuilder.git
cd TopologyBuilder
```

## How to Setup (Debian-based systems)

A virtual environment is strongly recommended, since `requirements.txt` was
frozen from a specific development machine and may pull in more than a
system Python wants:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`phart==2.1.0` (used by `visualize`'s ASCII rendering) is not published on
public PyPI as of this writing - if `pip install` fails on it, install the
latest available version instead (`pip install phart`); `visualize` may not
render correctly with a different version, but the rest of the CLI is
unaffected.

## Prerequisites

- Network access to the ESXi host and the GNS3 VM's management network.
- An ESXi host with a GNS3 VM already running, with a VLAN trunk NIC wired
  to a dedicated port group (see `esxi.trunk_port_group` below).
- The ESXi/GNS3 Template-API services this project queries for available
  image names (see `api.esxi_template_server_url`/`gns3_template_server_url`
  below) - or set `LITERAL_API_VALUES=true` to use the hardcoded template
  lists in `src/settings/settings.py` instead, for offline testing.

## Configuration

Two optional, git-ignored files let you avoid retyping the same values on
every invocation:

**`.env`** - copy [`.env.example`](.env.example) to `.env` and fill in
`ESXI_PASSWORD`/`GNS3_PASSWORD`. Loaded automatically via `python-dotenv`,
no flag needed. CLI flags (`--esxi_password`/`--gns3_password`) always take
precedence if both are given.

**`settings.yml`** - copy [`settings.example.yml`](settings.example.yml) to
`settings.yml` and override whichever keys you need (ESXi host/datastore/
trunk port group, GNS3 project name, Template-API URLs, etc. - see the
example file for the full list). Load it with `--settings settings.yml` (or
`-s settings.yml`). Only the keys you actually list get overridden; anything
you omit keeps its built-in default. **Passwords are not supported in this
file** - `initialise_settings()` refuses to load one containing a `password`
key, so a secret never ends up sitting in a file on disk; use `.env` or the
CLI password flags instead.

Every value can also just be passed as a CLI flag on the command that needs
it (see `topologybuilder <command> --help`) - `.env`/`settings.yml` exist
purely for convenience when a value would otherwise be retyped constantly.

## ESXi VM/Port Group Cleanup

A non-incremental `deploy` resets the ESXi vSwitch before wiring up the new
topology, which involves deleting port groups and (see below) VMs left over
from earlier deploys. Two safety mechanisms keep this from ever touching
anything this tool didn't create:

- **Port groups**: `esxi.trunk_port_group` and ESXi's own built-in `VM
  Network`/`Management Network` port groups are always protected from
  deletion, regardless of `esxi.ignore_port_groups`. Add any other port
  group you need preserved (e.g. a management NIC's port group) to
  `ignore_port_groups` in `settings.yml` - see
  [`settings.example.yml`](settings.example.yml) for a real example
  (`PG-MGMT`).
- **VMs**: every VM this tool imports is tagged with a
  `topologybuilder-image:<image>` annotation on creation. When
  `esxi.delete_unused_vms` is true (the default), a non-incremental `deploy`
  deletes any *tagged* VM that's no longer part of the current topology -
  cleaning up leftovers from an earlier deploy of a *different* topology,
  which would otherwise sit there indefinitely and could even block a
  port-group reset outright (ESXi refuses to delete a port group a VM's NIC
  is still attached to). The GNS3 VM is always auto-detected by name (any VM
  whose name contains `gns3`, case-insensitive) and is never deleted, no
  matter what `esxi.gns3_vm_name` is set to. A VM without the annotation -
  i.e. anything not created by this tool - is never touched, so this is safe
  to run on a shared ESXi host. Set `delete_unused_vms: false` in
  `settings.yml` to disable this cleanup entirely.

Both cleanup steps (and the vSwitch reset itself) are skipped entirely in
`--incremental` mode, which never removes anything.

## Topology Config File

The topology itself (what `validate`/`visualize`/`deploy` operate on) is a
separate YAML file with two top-level keys, `nodes` and `edges` - see
[`topology_example.yaml`](topology_example.yaml) for a full example.

`nodes` is a list of node groups, each sharing one image/role:

```yaml
nodes:
  - image: Cisco IOSv 15.6(1)T   # must match a GNS3 or ESXi template name
    role: ROUTER                 # one of: PC, VM, ROUTER, SWITCH, FW
    names:
      - ISP1-BB1
      - ISP1-BB2
```

`image` determines where the node ends up: an image found among the GNS3
server's own templates deploys as a GNS3 node; an image found among the ESXi
template catalog deploys as a full ESXi VM (`role: VM` is the natural choice
for these, but any role works - it's the image, not the role, that decides
the environment). The same image name may not exist on both catalogs at
once. Matching is case/whitespace-insensitive.

`edges` is a flat list of 4-element connections, `[node_a, interface_a,
node_b, interface_b]`:

```yaml
edges:
  - [ISP1-BB1, gi0/0, ISP1-BB2, gi0/0]
```

An edge between two GNS3-hosted nodes becomes a direct GNS3 link. An edge
touching an ESXi-hosted node gets bridged through a GNS3 Cloud node bound to
a VLAN subinterface on the GNS3 VM. An edge between two ESXi-hosted nodes
needs no GNS3-side wiring at all - both VMs' vNICs are placed on the same
VLAN-tagged port group.

An ESXi-hosted node's vNICs are wired positionally to its topology
interfaces, one port group per edge touching it. If the node's OVA template
itself declares *more* built-in networks than the node has edges (e.g. a
firewall appliance's OVA with a default WAN+LAN pair, deployed with only one
edge wired up in the topology), the extra OVA-declared network(s) reuse the
last edge's port group rather than failing the import - a warning is logged
when this happens. If the OVA declares *fewer* networks than the node has
edges, the remaining edges get added as new network adapters after import.

## Usage

| Command | Purpose |
|---|---|
| `topologybuilder validate` | Validate the topology file without building or deploying anything. |
| `topologybuilder visualize [--detail]` | Build the topology graph and print an ASCII visualization; `--detail` prints the full internal representation instead. |
| `topologybuilder deploy --address ... --esxi_username ... [--dry_run] [--incremental] [--only_on_gns3 \| --only_on_esxi]` | Validate, build, and deploy the topology to GNS3/ESXi. `--dry_run` prints what would happen without changing anything. `--incremental` reuses existing port groups/VMs/GNS3 project/nodes/links instead of recreating them - never removes anything dropped from the topology file. |
| `topologybuilder destroy --address ... --esxi_username ...` | Tear down a previously deployed topology: deletes its ESXi-hosted VMs/port groups and its GNS3 project's nodes. |
| `topologybuilder verify --address ... --esxi_username ...` | Structural health check against a deployed topology (GNS3 nodes started, ESXi VMs powered on with an IP, trunk NIC wiring, port groups present). Not a ping test - this project never assigns IP addresses to nodes, so there's no address to ping. |
| `topologybuilder status --address ... --esxi_username ...` | Check connectivity to the ESXi host and GNS3 VM, and list GNS3 projects with each one's node/started counts. No topology file needed. |
| `topologybuilder templates` | List available ESXi and GNS3 template names - valid values for a node's `image` field. |
| `topologybuilder portgroups --address ... --esxi_username ...` | List the port groups configured on the ESXi host's vSwitch. |
| `topologybuilder logs [--lines N]` | Show the last `N` (default 50) lines of the log file. |

Global options (`--verbosity`/`-v`, `--settings`/`-s`, `--topology`/`-t`,
`--literal_api_values`/`-l`) go **before** the subcommand name:
`python main.py -v d -t ./my_topology.yaml deploy ...`. Run
`python main.py <command> --help` for a command's full option list.

A typical first deploy, with nothing set in `.env`/`settings.yml`:

```bash
python main.py --topology ./topology_example.yaml deploy \
  --address 10.20.20.202 \
  --esxi_username root \
  --esxi_password '...'
```

## Testing

```bash
LITERAL_API_VALUES=true pytest tests
```

`LITERAL_API_VALUES=true` makes template-lookup calls return the hardcoded
literal set (see `src/settings/settings.py`) instead of hitting the real
template-listing services, so the suite runs without network access.

## License

GNU GPLv3 - see [LICENSE](LICENSE).
