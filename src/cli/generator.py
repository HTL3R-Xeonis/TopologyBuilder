"""CLI support for the Topology Generator website API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.graph import Graph

import os
import tempfile
from pathlib import Path

import typer

from src.settings import Settings


def generator_url(override: str | None = None) -> str:
    """Returns the configured Topology Generator API address."""
    url = override or os.environ.get("TOPOLOGY_GENERATOR_URL", "")
    if not url or not url.startswith(("http://", "https://")):
        raise typer.BadParameter("Set --generator-url or TOPOLOGY_GENERATOR_URL to an http(s) API address.")
    return url.rstrip("/")


def load_graph(path: Path) -> Graph:
    """Validates a topology file and returns its graph."""
    from src.graph import Graph
    from src.topology_file_validation import TopologyFileValidation

    validator = TopologyFileValidation(str(path))
    validator.validate_file()
    return Graph(validator.nodes, validator.edges)


def generate_topology(prompt: str, output: Path, url: str | None = None) -> Graph:
    """Generates a valid topology through the website API and saves its YAML."""
    import requests

    base_url = generator_url(url)
    max_retries = Settings.LLM.MAX_RETRIES if isinstance(Settings.LLM.MAX_RETRIES, int) else 2
    output = output.expanduser().resolve()
    if not output.parent.is_dir():
        raise typer.BadParameter(f"Output directory does not exist: {output.parent}")
    if output.suffix.lower() not in (".yml", ".yaml"):
        raise typer.BadParameter("Output must be a .yaml or .yml file.")

    for attempt in range(1, max_retries + 2):
        try:
            response = requests.post(
                f"{base_url}/api/generate-topology",
                json={"prompt": prompt},
                timeout=120,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            typer.secho(f"Generator API failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc

        if not isinstance(result, dict):
            typer.secho("Generator API returned an invalid response.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        for warning in result.get("warnings", []):
            typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW, err=True)
        if result.get("valid") is not True or not isinstance(result.get("yaml"), str):
            typer.secho(f"Generation attempt {attempt} returned no valid YAML.", fg=typer.colors.YELLOW, err=True)
            continue

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".yaml", prefix=".topology-", encoding="utf-8", dir=output.parent, delete=False
            ) as tmp:
                tmp.write(result["yaml"])
                tmp_path = Path(tmp.name)
            graph = load_graph(tmp_path)
            tmp_path.replace(output)
            typer.secho(f"Topology saved to {output}", fg=typer.colors.GREEN)
            return graph
        except (ValueError, TypeError, KeyError, RuntimeError, FileNotFoundError) as exc:
            typer.secho(f"Generation attempt {attempt} failed validation: {exc}", fg=typer.colors.YELLOW, err=True)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
    typer.secho(
        f"No valid topology after {max_retries + 1} attempts; existing output was not changed.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=1)
