"""Typer command-line interface for Course Courier."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .planner import CourierError, create_plan
from .staging import build as build_staging
from .staging import verify as verify_staging
from .workflow_init import MANUAL_CHECKLIST
from .workflow_init import init_workflow as init_workflow_scaffold

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


@app.command(name="init-workflow")
def init_workflow(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False, readable=True, help="Manifest path.")
    ],
    branch: Annotated[str, typer.Option("--branch", help="Private publishing branch.")] = "main",
    sha: Annotated[
        str | None,
        typer.Option("--sha", help="Immutable Course Courier commit SHA; skips remote tag resolution."),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Atomically replace an existing workflow file.")] = False,
) -> None:
    """Write the pinned publish workflow for this course at the Git work-tree root.

    Writes exactly one file, resolving this release's commit SHA from its version tag on the
    official repository unless --sha is given. The GitHub Environment, token secret, and branch
    protection remain manual steps, printed on success.
    """
    try:
        target = init_workflow_scaffold(config, branch=branch, sha=sha, force=force)
    except CourierError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(f"wrote {target}")
    for line in MANUAL_CHECKLIST:
        typer.echo(line)


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
