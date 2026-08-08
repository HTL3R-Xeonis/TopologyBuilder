# TopologyBuilder

A tool for building and deploying network topologies to GNS3/ESXi from a YAML config file.

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
