"""Manifest parsing and safe, side-effect-free publication planning."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

TRANSIENT_COMPONENTS = {".ipynb_checkpoints", "__pycache__", ".DS_Store"}
TRANSIENT_SUFFIXES = ("~", ".tmp", ".swp")


class CourierError(Exception):
    """An expected manifest or publication-plan validation error."""


@dataclass(frozen=True)
class PublicTarget:
    """The public GitHub repository and subtree owned by Course Courier."""

    repository: str
    branch: str
    managed_subtree: str

    def as_dict(self) -> dict[str, str]:
        return {
            "repository": self.repository,
            "branch": self.branch,
            "managed_subtree": self.managed_subtree,
        }


@dataclass(frozen=True)
class PlannedExport:
    """One validated source file and its public destination."""

    source: str
    destination: str
    size_bytes: int
    sha256: str
    executable: bool

    def as_dict(self) -> dict[str, str | int | bool]:
        return {
            "source": self.source,
            "destination": self.destination,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "executable": self.executable,
        }


@dataclass(frozen=True)
class NotebookPair:
    """A private Markdown authoring source paired with an exported notebook."""

    notebook: str
    markdown: str

    def as_dict(self) -> dict[str, str]:
        return {"notebook": self.notebook, "markdown": self.markdown}


@dataclass(frozen=True)
class NotebookTarget:
    """A version-2 Jupytext-root notebook staged under the unified notebook contract."""

    notebook: str
    destination: str
    markdown: str | None
    source_present: bool

    @property
    def generated(self) -> bool:
        return self.markdown is not None

    def as_dict(self) -> dict[str, str | bool]:
        entry: dict[str, str | bool] = {"destination": self.destination, "generated": self.generated}
        if self.markdown is not None:
            entry["markdown"] = self.markdown
        if self.source_present:
            entry["source"] = self.notebook
        return entry


@dataclass(frozen=True)
class DirectoryExpansion:
    """The per-entry accounting of one recursive release-list directory entry."""

    entry: str
    resolved: int
    excluded: int

    def as_dict(self) -> dict[str, str | int]:
        return {"entry": self.entry, "resolved": self.resolved, "excluded": self.excluded}


@dataclass(frozen=True)
class PublicationPlan:
    """The deterministic result of resolving a Course Courier manifest."""

    content_root: Path
    public: PublicTarget
    exports: tuple[PlannedExport, ...]
    notebook_pairs: tuple[NotebookPair, ...]
    manifest_sha256: str
    version: int = 1
    release_manifest: str | None = None
    release_manifest_sha256: str | None = None
    notebook_targets: tuple[NotebookTarget, ...] = ()
    directory_expansions: tuple[DirectoryExpansion, ...] = ()
    source_tracking: str | None = None

    def as_dict(self) -> dict[str, Any]:
        plan = {
            "version": self.version,
            "content_root": str(self.content_root),
            "public": self.public.as_dict(),
            "exports": [entry.as_dict() for entry in self.exports],
            "manifest_sha256": self.manifest_sha256,
        }
        if self.version >= 2:
            plan["release_manifest"] = self.release_manifest
            plan["release_manifest_sha256"] = self.release_manifest_sha256
            plan["notebook_targets"] = [target.as_dict() for target in self.notebook_targets]
            plan["source_tracking"] = self.source_tracking
            if self.directory_expansions:
                plan["directory_expansions"] = [expansion.as_dict() for expansion in self.directory_expansions]
        return plan

    def to_json(self) -> str:
        """Return the canonical JSON representation specified for `plan`."""
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def create_plan(config_path: Path) -> PublicationPlan:
    """Parse, validate, and resolve a manifest without writing files."""
    config_path = Path(config_path)
    try:
        manifest_bytes = config_path.read_bytes()
    except OSError as error:
        raise CourierError(f"{config_path}: cannot read configuration: {error.strerror or error}") from error

    try:
        manifest = tomllib.loads(manifest_bytes.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise CourierError(f"{config_path}: configuration must be UTF-8: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise CourierError(f"{config_path}: invalid TOML: {error}") from error

    if not isinstance(manifest, dict):
        raise CourierError(f"{config_path}: manifest must be a TOML table")
    version = _require_version(config_path, manifest.get("version"))
    content_root = config_path.parent.resolve()
    _validate_content_root(config_path, content_root)

    if version == 2:
        from .release_list import create_plan_v2

        return create_plan_v2(config_path, content_root, manifest, manifest_bytes)

    _reject_unknown_fields(config_path, manifest, {"version", "public", "export", "notebook"}, "manifest")
    public = _parse_public(config_path, manifest.get("public"))
    raw_exports = manifest.get("export")
    if not isinstance(raw_exports, list) or not raw_exports:
        raise CourierError(f"{config_path}: `export` must contain one or more entries")
    entries = _resolve_exports(config_path, content_root, public.managed_subtree, raw_exports)
    notebook_pairs = _parse_notebook_pairs(config_path, content_root, manifest.get("notebook", []), entries)
    return PublicationPlan(
        content_root=content_root,
        public=public,
        exports=tuple(sorted(entries, key=lambda entry: entry.destination)),
        notebook_pairs=tuple(sorted(notebook_pairs, key=lambda pair: pair.notebook)),
        manifest_sha256=sha256(manifest_bytes).hexdigest(),
    )


def _parse_notebook_pairs(
    config_path: Path, content_root: Path, raw_pairs: object, exports: list[PlannedExport]
) -> list[NotebookPair]:
    if not isinstance(raw_pairs, list):
        raise CourierError(f"{config_path}: `notebook` must contain notebook tables")
    export_sources = {entry.source for entry in exports}
    pairs: list[NotebookPair] = []
    notebooks: set[str] = set()
    markdown_sources: set[str] = set()
    for number, raw_pair in enumerate(raw_pairs, start=1):
        label = f"notebook entry {number}"
        if not isinstance(raw_pair, dict):
            raise CourierError(f"{config_path}: {label} must be a table")
        _reject_unknown_fields(config_path, raw_pair, {"notebook", "markdown"}, label)
        notebook = _require_string(config_path, raw_pair, "notebook", label)
        markdown = _require_string(config_path, raw_pair, "markdown", label)
        _validate_relative_path(config_path, notebook, f"{label}.notebook")
        markdown_parts = _validate_relative_path(config_path, markdown, f"{label}.markdown")
        if not notebook.endswith(".ipynb") or not markdown.endswith(".md"):
            raise CourierError(f"{config_path}: {label} must pair an `.ipynb` notebook with a `.md` Markdown source")
        if notebook not in export_sources:
            raise CourierError(f"{config_path}: {label}.notebook is not an exported source: `{notebook}`")
        if notebook in notebooks or markdown in markdown_sources:
            raise CourierError(f"{config_path}: {label} duplicates a declared notebook or Markdown source")
        _validate_transient_path(config_path, markdown, markdown_parts, f"{label}.markdown")
        _validate_source(config_path, content_root, content_root.joinpath(*markdown_parts), markdown, label)
        notebooks.add(notebook)
        markdown_sources.add(markdown)
        pairs.append(NotebookPair(notebook=notebook, markdown=markdown))
    return pairs


def _require_version(config_path: Path, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in {1, 2}:
        raise CourierError(f"{config_path}: `version` must be the integer 1 or 2")
    return value


def _parse_public(config_path: Path, value: object) -> PublicTarget:
    if not isinstance(value, dict):
        raise CourierError(f"{config_path}: `public` must be a table")
    _reject_unknown_fields(config_path, value, {"repository", "branch", "managed_subtree"}, "public")
    repository = _require_string(config_path, value, "repository", "public")
    branch = _require_string(config_path, value, "branch", "public")
    managed_subtree = _require_string(config_path, value, "managed_subtree", "public")
    repository_parts = repository.split("/")
    if len(repository_parts) != 2 or not all(repository_parts):
        raise CourierError(f"{config_path}: `public.repository` must be an `owner/repository` identifier")
    _validate_branch(config_path, branch)
    _validate_managed_subtree(config_path, managed_subtree)
    return PublicTarget(repository=repository, branch=branch, managed_subtree=managed_subtree)


def _resolve_exports(
    config_path: Path, content_root: Path, managed_subtree: str, raw_exports: list[object]
) -> list[PlannedExport]:
    planned: list[PlannedExport] = []
    sources: set[str] = set()
    destinations: set[str] = set()
    folded_destinations: dict[str, str] = {}

    for number, raw_entry in enumerate(raw_exports, start=1):
        label = f"export entry {number}"
        if not isinstance(raw_entry, dict):
            raise CourierError(f"{config_path}: {label} must be a table")
        _reject_unknown_fields(config_path, raw_entry, {"source", "destination"}, label)
        source = _require_string(config_path, raw_entry, "source", label)
        destination = _require_string(config_path, raw_entry, "destination", label)
        source_parts = _validate_relative_path(config_path, source, f"{label}.source")
        destination_parts = _validate_relative_path(config_path, destination, f"{label}.destination")
        _reject_git_component(config_path, destination_parts, f"{label}.destination")
        _validate_transient_path(config_path, source, source_parts, f"{label}.source")

        if source in sources:
            raise CourierError(f"{config_path}: {label}.source duplicates `{source}`")
        sources.add(source)

        final_destination = destination if managed_subtree == "." else f"{managed_subtree}/{destination}"
        if final_destination in destinations:
            raise CourierError(
                f"{config_path}: {label}.destination duplicates resolved destination `{final_destination}`"
            )
        folded_destination = final_destination.casefold()
        if folded_destination in folded_destinations:
            other = folded_destinations[folded_destination]
            raise CourierError(f"{config_path}: {label}.destination collides case-insensitively with `{other}`")
        destinations.add(final_destination)
        folded_destinations[folded_destination] = destination

        source_path = content_root.joinpath(*source_parts)
        _validate_source(config_path, content_root, source_path, source, label)
        planned.append(
            PlannedExport(
                source=source,
                destination=final_destination,
                size_bytes=source_path.stat().st_size,
                sha256=_sha256_file(source_path),
                executable=_is_executable(source_path),
            )
        )

    _reject_destination_ancestors(config_path, destinations)
    return planned


def _reject_unknown_fields(config_path: Path, value: dict[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        fields = ", ".join(f"`{field}`" for field in unknown)
        raise CourierError(f"{config_path}: {label} contains unknown field(s): {fields}")


def _require_string(config_path: Path, value: dict[str, object], key: str, label: str) -> str:
    field = value.get(key)
    if not isinstance(field, str) or not field:
        raise CourierError(f"{config_path}: `{label}.{key}` must be a non-empty string")
    return field


def _validate_relative_path(config_path: Path | str, value: str, field: str) -> tuple[str, ...]:
    if "\\" in value or value.startswith("/") or value.endswith("/") or "//" in value:
        raise CourierError(f"{config_path}: `{field}` must be a safe relative POSIX path")
    parts = tuple(value.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise CourierError(f"{config_path}: `{field}` must be a safe relative POSIX path")
    pure_path = PurePosixPath(value)
    if pure_path.is_absolute() or any(part in {".", ".."} for part in pure_path.parts):
        raise CourierError(f"{config_path}: `{field}` must be a safe relative POSIX path")
    return parts


def _validate_managed_subtree(config_path: Path, value: str) -> None:
    if value == ".":
        return
    parts = _validate_relative_path(config_path, value, "public.managed_subtree")
    _reject_git_component(config_path, parts, "public.managed_subtree")


def _validate_branch(config_path: Path | str, value: str, field: str = "public.branch") -> None:
    if value in {"@", "HEAD"} or value.startswith("-"):
        raise CourierError(f"{config_path}: `{field}` is not a valid Git branch name")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        raise CourierError(f"{config_path}: `{field}` is not a valid Git branch name")
    if any(character in "~^:?*[\\" for character in value):
        raise CourierError(f"{config_path}: `{field}` is not a valid Git branch name")
    if value.startswith("/") or value.endswith("/") or "//" in value or ".." in value or "@{" in value:
        raise CourierError(f"{config_path}: `{field}` is not a valid Git branch name")
    components = value.split("/")
    if any(component.startswith(".") or component.endswith((".", ".lock")) for component in components):
        raise CourierError(f"{config_path}: `{field}` is not a valid Git branch name")


def _reject_git_component(config_path: Path | str, parts: tuple[str, ...], field: str) -> None:
    if ".git" in parts:
        raise CourierError(f"{config_path}: `{field}` must not contain a `.git` path component")


def _validate_content_root(config_path: Path, content_root: Path) -> None:
    if not content_root.is_dir():
        raise CourierError(f"{config_path}: content root is not a directory")


def _validate_transient_path(config_path: Path | str, source: str, parts: tuple[str, ...], field: str) -> None:
    if any(part in TRANSIENT_COMPONENTS or part.startswith(".~") for part in parts):
        raise CourierError(f"{config_path}: `{field}` is transient and cannot be published: `{source}`")
    if parts[-1] == ".DS_Store" or parts[-1].endswith(TRANSIENT_SUFFIXES):
        raise CourierError(f"{config_path}: `{field}` is transient and cannot be published: `{source}`")


def _validate_source(
    config_path: Path | str, content_root: Path, source_path: Path, source: str, label: str
) -> None:
    current = content_root
    for part in PurePosixPath(source).parts:
        current = current / part
        if current.is_symlink():
            raise CourierError(f"{config_path}: {label}.source contains a symbolic link: `{source}`")
    if not source_path.exists():
        raise CourierError(f"{config_path}: {label}.source does not exist: `{source}`")
    if not source_path.is_file():
        raise CourierError(f"{config_path}: {label}.source is not a regular file: `{source}`")
    try:
        source_path.resolve(strict=True).relative_to(content_root)
    except ValueError as error:
        raise CourierError(f"{config_path}: {label}.source escapes the content root: `{source}`") from error


def _reject_destination_ancestors(config_path: Path | str, destinations: set[str]) -> None:
    for destination in destinations:
        for ancestor in PurePosixPath(destination).parents:
            if str(ancestor) in destinations:
                raise CourierError(f"{config_path}: destination `{ancestor}` conflicts with descendant `{destination}`")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)
