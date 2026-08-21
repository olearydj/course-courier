"""Deterministic construction and validation of local publication staging trees."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

import jupytext
import nbformat
import yaml

from .planner import CourierError, NotebookPair, PlannedExport, PublicationPlan, create_plan


@dataclass(frozen=True)
class StagedInventory:
    """A validated plan paired with the output tree that realizes it."""

    plan: PublicationPlan
    output_root: Path
    notebook_exports: tuple[StagedNotebook, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        inventory = self.plan.as_dict()
        inventory["output_root"] = str(self.output_root)
        if self.notebook_exports:
            inventory["notebook_exports"] = [entry.as_dict() for entry in self.notebook_exports]
        return inventory

    def to_json(self) -> str:
        """Return the canonical JSON representation for `build` and `verify`."""
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


@dataclass(frozen=True)
class StagedNotebook:
    """The normalized staged representation of a declared notebook pair."""

    source: str
    markdown: str
    destination: str
    size_bytes: int
    sha256: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "source": self.source,
            "markdown": self.markdown,
            "destination": self.destination,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


def build(config_path: Path, output_path: Path) -> StagedInventory:
    """Create a new staged tree from a validated plan without touching existing output."""
    plan = create_plan(config_path)
    output_path = _prepare_new_output_path(output_path)
    staged_notebooks = _staged_notebooks(plan)
    notebook_destinations = {entry.destination: entry for entry in staged_notebooks}
    temporary_root: Path | None = None

    try:
        temporary_root = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.", dir=output_path.parent))
        for entry in plan.exports:
            source_path = _source_path(plan, entry.source)
            destination_path = _output_path(temporary_root, entry.destination)
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            notebook = notebook_destinations.get(entry.destination)
            if notebook is None:
                _copy_export(source_path, destination_path, entry.size_bytes, entry.sha256, entry.executable)
            else:
                _write_normalized_notebook(source_path, destination_path, notebook, entry.executable)

        _verify_tree(plan, temporary_root, notebook_destinations)
        if os.path.lexists(output_path):
            raise CourierError(f"{output_path}: output path was created while build was running")
        temporary_root.rename(output_path)
        temporary_root = None
    except OSError as error:
        raise CourierError(f"{output_path}: could not build staged output: {error.strerror or error}") from error
    finally:
        if temporary_root is not None:
            shutil.rmtree(temporary_root, ignore_errors=True)

    inventory = StagedInventory(plan=plan, output_root=output_path.resolve(), notebook_exports=tuple(staged_notebooks))
    _verify_tree(plan, inventory.output_root, notebook_destinations)
    return inventory


def verify(config_path: Path, output_path: Path) -> StagedInventory:
    """Validate an existing staged tree against a newly resolved plan."""
    plan = create_plan(config_path)
    output_root = _existing_output_root(output_path)
    staged_notebooks = _staged_notebooks(plan)
    notebook_destinations = {entry.destination: entry for entry in staged_notebooks}
    _verify_tree(plan, output_root, notebook_destinations)
    return StagedInventory(plan=plan, output_root=output_root, notebook_exports=tuple(staged_notebooks))


def _prepare_new_output_path(output_path: Path) -> Path:
    output_path = Path(output_path).absolute()
    if os.path.lexists(output_path):
        raise CourierError(f"{output_path}: output path must not already exist")
    if not output_path.parent.is_dir():
        raise CourierError(f"{output_path}: output parent directory does not exist")
    return output_path


def _existing_output_root(output_path: Path) -> Path:
    output_path = Path(output_path)
    if output_path.is_symlink() or not output_path.is_dir():
        raise CourierError(f"{output_path}: output path must be an existing non-symbolic-link directory")
    return output_path.resolve()


def _source_path(plan: PublicationPlan, source: str) -> Path:
    return plan.content_root.joinpath(*PurePosixPath(source).parts)


def _output_path(output_root: Path, destination: str) -> Path:
    path = output_root.joinpath(*PurePosixPath(destination).parts)
    try:
        path.relative_to(output_root)
    except ValueError as error:
        raise CourierError(f"{destination}: destination escapes the output root") from error
    return path


def _copy_export(
    source_path: Path, destination_path: Path, expected_size: int, expected_sha256: str, expected_executable: bool
) -> None:
    if source_path.is_symlink() or not source_path.is_file():
        raise CourierError(f"{source_path}: planned source is no longer a regular file")
    if _is_executable(source_path) != expected_executable:
        raise CourierError(f"{source_path}: source mode changed while the staged copy was being built")
    shutil.copyfile(source_path, destination_path)
    _set_normalized_mode(destination_path, expected_executable)
    actual_size, actual_sha256 = _file_details(destination_path)
    if actual_size != expected_size or actual_sha256 != expected_sha256:
        raise CourierError(f"{source_path}: source changed while the staged copy was being built")


def _verify_tree(plan: PublicationPlan, output_root: Path, notebook_destinations: dict[str, StagedNotebook]) -> None:
    expected_files = {entry.destination for entry in plan.exports}
    expected_directories = _expected_directories(expected_files)
    errors: list[str] = []

    for entry in plan.exports:
        staged_path = _output_path(output_root, entry.destination)
        _reject_symbolic_link_components(output_root, staged_path, entry.destination, errors)
        if staged_path.is_symlink() or not staged_path.is_file():
            errors.append(f"missing or non-regular staged file: `{entry.destination}`")
            continue
        size_bytes, digest = _file_details(staged_path)
        expected_size, expected_digest = _expected_details(entry, notebook_destinations)
        if size_bytes != expected_size or digest != expected_digest or _is_executable(staged_path) != entry.executable:
            errors.append(f"staged file does not match plan: `{entry.destination}`")

    boundary = _managed_boundary(plan, output_root)
    _reject_symbolic_link_components(output_root, boundary, plan.public.managed_subtree, errors)
    if boundary.is_symlink() or not boundary.is_dir():
        errors.append(f"managed boundary is missing or not a directory: `{plan.public.managed_subtree}`")
    else:
        errors.extend(_unexpected_entries(output_root, boundary, expected_files, expected_directories))

    if errors:
        raise CourierError(f"{output_root}: staged output does not match plan: {'; '.join(sorted(errors))}")


def _managed_boundary(plan: PublicationPlan, output_root: Path) -> Path:
    if plan.public.managed_subtree == ".":
        return output_root
    return _output_path(output_root, plan.public.managed_subtree)


def _expected_directories(expected_files: set[str]) -> set[str]:
    directories: set[str] = set()
    for destination in expected_files:
        directories.update(str(parent) for parent in PurePosixPath(destination).parents if str(parent) != ".")
    return directories


def _reject_symbolic_link_components(output_root: Path, path: Path, label: str, errors: list[str]) -> None:
    try:
        relative_parts = path.relative_to(output_root).parts
    except ValueError:
        errors.append(f"path escapes output root: `{label}`")
        return
    current = output_root
    for part in relative_parts:
        current /= part
        if current.is_symlink():
            errors.append(f"symbolic link in staged path: `{label}`")
            return


def _unexpected_entries(
    output_root: Path, boundary: Path, expected_files: set[str], expected_directories: set[str]
) -> list[str]:
    unexpected: list[str] = []
    for current_root, directory_names, file_names in os.walk(boundary, followlinks=False):
        current = Path(current_root)
        for name in directory_names:
            path = current / name
            relative = path.relative_to(output_root).as_posix()
            if path.is_symlink():
                unexpected.append(f"unexpected symbolic link: `{relative}`")
            elif relative not in expected_directories:
                unexpected.append(f"unexpected directory: `{relative}`")
        for name in file_names:
            path = current / name
            relative = path.relative_to(output_root).as_posix()
            if path.is_symlink():
                unexpected.append(f"unexpected symbolic link: `{relative}`")
            elif relative not in expected_files:
                unexpected.append(f"unexpected file: `{relative}`")
    return unexpected


def _file_details(path: Path) -> tuple[int, str]:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return path.stat().st_size, digest.hexdigest()


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)


def _set_normalized_mode(path: Path, executable: bool) -> None:
    path.chmod(0o755 if executable else 0o644)


def _staged_notebooks(plan: PublicationPlan) -> list[StagedNotebook]:
    export_destinations = {entry.source: entry.destination for entry in plan.exports}
    staged: list[StagedNotebook] = []
    for pair in plan.notebook_pairs:
        source_path = _source_path(plan, pair.notebook)
        _validate_notebook_pair(plan, pair)
        contents = _normalized_notebook_bytes(source_path)
        staged.append(
            StagedNotebook(
                source=pair.notebook,
                markdown=pair.markdown,
                destination=export_destinations[pair.notebook],
                size_bytes=len(contents),
                sha256=sha256(contents).hexdigest(),
            )
        )
    return sorted(staged, key=lambda entry: entry.destination)


def _validate_notebook_pair(plan: PublicationPlan, pair: NotebookPair) -> None:
    notebook_path = _source_path(plan, pair.notebook)
    markdown_path = _source_path(plan, pair.markdown)
    try:
        private_notebook = nbformat.read(notebook_path, as_version=4)
        markdown_notebook = jupytext.read(markdown_path)
        private_contents = _pair_comparison_bytes(private_notebook)
        markdown_contents = _pair_comparison_bytes(markdown_notebook)
    except (OSError, nbformat.ValidationError, ValueError, yaml.YAMLError) as error:
        raise CourierError(f"{notebook_path}: cannot validate notebook pair: {error}") from error
    if private_contents != markdown_contents:
        raise CourierError(f"{notebook_path}: declared Markdown pair is out of sync: `{pair.markdown}`")


def _write_normalized_notebook(
    source_path: Path, destination_path: Path, expected: StagedNotebook, expected_executable: bool
) -> None:
    if _is_executable(source_path) != expected_executable:
        raise CourierError(f"{source_path}: source mode changed while the staged copy was being built")
    contents = _normalized_notebook_bytes(source_path)
    if len(contents) != expected.size_bytes or sha256(contents).hexdigest() != expected.sha256:
        raise CourierError(f"{source_path}: notebook changed while the staged copy was being built")
    destination_path.write_bytes(contents)
    _set_normalized_mode(destination_path, expected_executable)


def _expected_details(entry: PlannedExport, notebook_destinations: dict[str, StagedNotebook]) -> tuple[int, str]:
    notebook = notebook_destinations.get(entry.destination)
    if notebook is not None:
        return notebook.size_bytes, notebook.sha256
    return entry.size_bytes, entry.sha256


def _normalized_notebook_bytes(path: Path) -> bytes:
    try:
        notebook = nbformat.read(path, as_version=4)
    except (OSError, nbformat.ValidationError, ValueError) as error:
        raise CourierError(f"{path}: invalid notebook: {error}") from error
    return _normalized_notebook_bytes_from_node(notebook)


def _normalized_notebook_bytes_from_node(notebook: Any) -> bytes:
    normalized = deepcopy(notebook)
    for index, cell in enumerate(normalized.cells):
        if cell.cell_type == "code":
            cell.execution_count = None
            cell.outputs = []
        cell.setdefault("id", f"course-courier-{index}")
    try:
        nbformat.validate(normalized)
        return nbformat.writes(normalized, version=4).encode("utf-8")
    except (nbformat.ValidationError, ValueError) as error:
        raise CourierError(f"invalid notebook: {error}") from error


def _pair_comparison_bytes(notebook: Any) -> bytes:
    normalized = deepcopy(notebook)
    for index, cell in enumerate(normalized.cells):
        if cell.cell_type == "code":
            cell.execution_count = None
            cell.outputs = []
        cell.setdefault("id", f"course-courier-{index}")
    try:
        nbformat.validate(normalized)
    except (nbformat.ValidationError, ValueError) as error:
        raise CourierError(f"invalid notebook: {error}") from error
    for cell in normalized.cells:
        cell.pop("id", None)
    normalized.pop("nbformat_minor", None)
    jupytext_metadata = normalized.metadata.get("jupytext")
    if jupytext_metadata is not None:
        jupytext_metadata.pop("text_representation", None)
        if not jupytext_metadata:
            normalized.metadata.pop("jupytext", None)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
