"""Typer command-line interface for Course Courier."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .planner import CourierError, create_plan
from .staging import build as build_staging
from .staging import verify as verify_staging

app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="Safely plan allowlisted publication of course content."
)


@app.callback()
def main() -> None:
    """Safely plan allowlisted publication of course content."""


@app.command()
def plan(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False, readable=True, help="Manifest path.")
    ],
) -> None:
    """Resolve a manifest into a deterministic publication plan."""
    try:
        publication_plan = create_plan(config)
    except CourierError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(publication_plan.to_json(), nl=False)


@app.command()
def build(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False, readable=True, help="Manifest path.")
    ],
    output: Annotated[Path, typer.Option("--output", help="New staging-directory path.")],
) -> None:
    """Create a clean staged public tree at a new output path."""
    try:
        inventory = build_staging(config, output)
    except CourierError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(inventory.to_json(), nl=False)


@app.command()
def verify(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False, readable=True, help="Manifest path.")
    ],
    output: Annotated[Path, typer.Option("--output", help="Existing staging-directory path.")],
) -> None:
    """Verify an existing staged public tree against its manifest."""
    try:
        inventory = verify_staging(config, output)
    except CourierError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(inventory.to_json(), nl=False)
