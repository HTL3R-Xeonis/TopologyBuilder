# TopologyBuilder

A CLI tool that takes a YAML topology description (nodes + edges, each node with an
`image`/`role`) and deploys it as a real, running network lab across two systems:

- **GNS3** — for network-device nodes (routers, switches, PCs via VPCS). Runs on a
  dedicated GNS3 VM.
- **ESXi** — for full VM nodes (e.g. an Ubuntu Server, a Rocky Linux box). Runs
  directly on an ESXi host.

The two environments are bridged at the network layer: ESXi VMs and GNS3 devices
that are topologically connected reach each other over VLAN-tagged links, with
GNS3's Cloud node type acting as the bridge endpoint inside GNS3.

## How to Download

Clone the repository:

```bash
git clone https://github.com/HTL3R-Xeonis/TopologyBuilder.git
```

Or, if you use SSH:

```bash
git clone git@github.com:HTL3R-Xeonis/TopologyBuilder.git
```

Then move into the project directory:

```bash
cd TopologyBuilder
```

## How to Setup (Debian-based systems)

Install the required system packages:

```bash
sudo apt update
```
```bash
sudo apt install -y python3 python3-venv python3-pip
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
```
```bash
source .venv/bin/activate
```

Install the Python dependencies and the CLI itself (editable install, so code changes take effect immediately):

```bash
pip install --upgrade pip
```
```bash
pip install -r requirements.txt
```
```bash
pip install -e .
```

Verify the CLI is available:

```bash
topologybuilder --help
```

Whenever you open a new terminal, re-activate the virtual environment before using the CLI:

```bash
source .venv/bin/activate
```

## Prerequisites

`topologybuilder deploy` talks to several external systems, all of which must
already exist and be reachable:

- An **ESXi host**, reachable directly (not through vCenter), with a
  pre-existing trunk port group for the GNS3 VM's VLAN trunk NIC (see
  `gns3_trunk_network` below) and, if the topology has `role: VM` nodes, a
  datastore with enough free space for their OVAs.
- A **GNS3 VM** already running on that ESXi host, reachable over SSH with the
  stock GNS3 VM appliance credentials (`gns3`/`gns3`) and over HTTP on its v2
  controller API (port 80).
- Two internal template-listing/OVA-download services that this project's
  ESXi and GNS3 template lookups depend on. Their base URLs are currently
  hardcoded in `src/connections_handler.py`
  (`_ESXI_TEMPLATE_API_BASE_URL`, `_GNS3_TEMPLATE_API_BASE_URL`) rather than
  configurable, so this tool assumes access to that specific internal
  network. `LITERAL_API_VALUES=true` (see Testing below) bypasses both for
  local development/testing without that network.

## Configuration

CLI option defaults can be set once in a `topologybuilder.yml` file (or
`topologybuilder.yaml`) in the working directory, or via the
`TOPOLOGYBUILDER_CONFIG` environment variable pointing at one elsewhere. See
[`topologybuilder.example.yml`](topologybuilder.example.yml) for every
supported key and what it controls — copy it to `topologybuilder.yml` (already
git-ignored) and fill in your own values.

CLI flags and environment variables always take precedence over this file. The
ESXi password is intentionally never read from it — pass `--esxi-password`,
set `ESXI_PASSWORD`, or let the CLI prompt for it interactively instead.

## Topology Config File

The topology itself (what `validate`/`build`/`deploy` operate on) is a
separate YAML file with two top-level keys, `nodes` and `edges` — see
[`config_file_example.yml`](config_file_example.yml) for a full example.

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
for these, but any role works — it's the image, not the role, that decides
the environment). The same image name may not exist on both catalogs at once.

`edges` is a flat list of 4-element connections, `[node_a, interface_a,
node_b, interface_b]`:

```yaml
edges:
  - [ISP1-BB1, gi0/0, ISP1-BB2, gi0/0]
```

An edge between two GNS3-hosted nodes becomes a direct GNS3 link. An edge
touching an ESXi-hosted node gets bridged through a GNS3 Cloud node bound to a
VLAN subinterface on the GNS3 VM. An edge between two ESXi-hosted nodes needs
no GNS3-side wiring at all — VLAN assignment alone puts both VMs' vNICs on the
same port group.

## Usage

| Command | Purpose |
|---|---|
| `topologybuilder validate <config>` | Validate a topology config file without building or deploying anything. |
| `topologybuilder build <config> [--graph] [--list]` | Validate and build the in-memory topology graph; optionally print an ASCII visualization (`--graph`) or a connection tree (`--list`). |
| `topologybuilder generate <prompt>` | Generate a topology config file from a natural-language prompt via the Topology Generator API. |
| `topologybuilder deploy <config> --esxi-host ... --esxi-username ...` | Validate, build, and deploy the topology to GNS3/ESXi. |
| `topologybuilder portgroups --esxi-host ... --esxi-username ...` | List the port groups configured on the ESXi host's vSwitches. |

Every command accepts `-v`/`-vv` for more verbose console logging, or `-q` to
suppress everything but errors (the log file at `logs/log.txt` always records
everything regardless). Run `topologybuilder <command> --help` for the full,
current option list — options that have config-file/env-var equivalents (like
`--esxi-host`) are documented there too.

A typical first deploy, with nothing set in `topologybuilder.yml`:

```bash
topologybuilder deploy ./config_file_example.yml \
  --esxi-host 10.20.20.202 \
  --esxi-username root \
  --esxi-datastore datastore1 \
  --gns3-trunk-network PG-GNS3-TRUNK
```

Replacing the GNS3 VM itself from a fresh OVA first (`--fresh-gns3-vm`) needs
four more flags — `--gns3-ova-path`, `--gns3-datastore`,
`--gns3-mgmt-network`, and `--gns3-trunk-network` (already required above) —
see `deploy --help` for details.

## Testing

```bash
LITERAL_API_VALUES=true pytest tests -q
```

`LITERAL_API_VALUES=true` makes template-lookup calls return a hardcoded
literal set (see `src/settings.py`) instead of hitting the real
template-listing services, so the suite runs without network access.

## License

GNU GPLv3 — see [LICENSE](LICENSE).
