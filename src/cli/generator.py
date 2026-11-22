"""CLI support for the Topology Generator website API."""

from __future__ import annotations

import tempfile
from pathlib import Path

import typer
from loguru import logger

from src.connections.topology_generator_connection import TopologyGeneratorConnection
from src.settings import Settings


def generator_url(override: str | None = None) -> str:
    """
    Returns the configured generator API address.
    :param override: Optional API address for this request.
    :return: Normalized HTTP API URL.
    :raises typer.BadParameter: If the API address is invalid.
    """
    url = override if override is not None else Settings.API.TOPOLOGY_GENERATOR_URL
    if not isinstance(url, str) or not url.strip().startswith(("http://", "https://")):
        raise typer.BadParameter("Set an http(s) generator API URL via --generator-url or the settings.")
    return url.strip().rstrip("/")


def load_graph(path: Path):
    """
    Validates a topology file and returns its graph.
    :param path: Topology YAML path.
    :return: Validated topology graph.
    :raises FileNotFoundError: If the topology file is missing.
    :raises ValueError: If the topology is invalid.
    :raises KeyError: If required topology fields are missing.
    :raises TypeError: If topology fields have invalid types.
    :raises TimeoutError: If the template service cannot respond in time.
    """
    from src.graph import Graph
    from src.topology_file_validation import TopologyFileValidation

    validator = TopologyFileValidation(str(path))
    validator.validate_file()
    return Graph(validator.nodes, validator.edges)


def generate_topology(prompt: str, output: Path, url: str | None = None):
    """
    Generates, validates, and saves a topology configuration.
    :param prompt: Natural-language topology description.
    :param output: Destination YAML file.
    :param url: Optional generator API URL.
    :return: Graph for the saved topology.
    :raises typer.BadParameter: If the input or destination is invalid.
    :raises typer.Exit: If no valid topology can be generated.
    :raises TimeoutError: If the generator request times out.
    :raises RuntimeError: If the generator service fails.
    :raises OSError: If the output cannot be written.
    """
    if not prompt.strip():
        raise typer.BadParameter("The topology description must not be empty.")
    output = output.expanduser().resolve()
    if not output.parent.is_dir():
        raise typer.BadParameter(f"Output directory does not exist: {output.parent}")
    if output.suffix.lower() not in (".yml", ".yaml"):
        raise typer.BadParameter("Output must be a .yaml or .yml file.")

    api_url = generator_url(url)
    retries = Settings.API.GENERATOR.MAX_RETRIES
    logger.info("Topology generation started: output={}, max_attempts={}", output, retries + 1)
    for attempt in range(1, retries + 2):
        result = TopologyGeneratorConnection.generate_topology(prompt, url=api_url)
        warnings = result.get("warnings") or []
        if not isinstance(warnings, list):
            warnings = [warnings]
        for warning in warnings:
            logger.warning("Generator attempt {}/{}: {}", attempt, retries + 1, warning)
            typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW, err=True)

        generated_yaml = result.get("yaml")
        if result.get("valid") is not True or not isinstance(generated_yaml, str) or not generated_yaml.strip():
            logger.warning("Generator attempt {}/{} returned invalid topology", attempt, retries + 1)
            typer.secho(
                f"Attempt {attempt}/{retries + 1}: generator did not return valid YAML.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            continue

        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".yaml",
                prefix=".topology-",
                dir=output.parent,
                delete=False,
            ) as temporary:
                temporary.write(generated_yaml)
                temporary_path = Path(temporary.name)
            try:
                graph = load_graph(temporary_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Generator attempt {}/{} failed validation: {}", attempt, retries + 1, exc)
                typer.secho(
                    f"Attempt {attempt}/{retries + 1}: topology validation failed: {exc}",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
                continue
            temporary_path.replace(output)
            logger.info("Topology generation completed: output={}, attempt={}", output, attempt)
            typer.secho(f"Topology saved to {output}", fg=typer.colors.GREEN)
            return graph
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    logger.error("Topology generation exhausted {} attempts; output unchanged: {}", retries + 1, output)
    typer.secho(
        f"No valid topology after {retries + 1} attempts; existing output was not changed.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(code=1)
