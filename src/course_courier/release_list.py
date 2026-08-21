"""Version-2 release-list parsing, directory expansion, and plan resolution."""

from __future__ import annotations

import codecs
import os
import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .planner import (
    TRANSIENT_COMPONENTS,
    TRANSIENT_SUFFIXES,
    CourierError,
    DirectoryExpansion,
    NotebookTarget,
    PlannedExport,
    PublicationPlan,
    _is_executable,
    _parse_public,
    _reject_destination_ancestors,
    _reject_git_component,
    _reject_unknown_fields,
    _sha256_file,
    _validate_relative_path,
    _validate_source,
    _validate_transient_path,
)

ARROW = " -> "
NOTEBOOK_SUFFIX = ".ipynb"
MARKDOWN_SUFFIX = ".md"


@dataclass(frozen=True)
class ReleaseEntry:
    """One parsed, path-validated release-list line."""

    line_number: int
    source: str
    destination: str
    directory: bool


def create_plan_v2(
    config_path: Path, content_root: Path, manifest: dict[str, object], manifest_bytes: bytes
) -> PublicationPlan:
    """Resolve a version-2 manifest and its release list into a publication plan."""
    _reject_unknown_fields(config_path, manifest, {"version", "release_manifest", "public", "notebooks"}, "manifest")
    public = _parse_public(config_path, manifest.get("public"))
    release_manifest, release_path = _parse_release_manifest_field(config_path, content_root, manifest)
    notebook_roots = _parse_notebook_roots(config_path, content_root, manifest.get("notebooks"))

    release_display = config_path.parent.joinpath(*release_manifest.split("/"))
    try:
        release_bytes = release_path.read_bytes()
    except OSError as error:
        raise CourierError(f"{release_display}: cannot read release list: {error.strerror or error}") from error

    entries = _parse_release_lines(release_display, release_bytes)
    if not entries:
        raise CourierError(f"{release_display}: release list contains no entries")
    _reject_duplicate_and_overlapping_entries(release_display, entries, notebook_roots)

    reserved = {config_path.name, release_manifest}
    exports: list[PlannedExport] = []
    targets: list[NotebookTarget] = []
    expansions: list[DirectoryExpansion] = []
    destinations: dict[str, str] = {}
    folded_destinations: dict[str, str] = {}
    tracked: set[str] | None = None
    tracking: str | None = None

    def register_destination(context: str, final_destination: str) -> None:
        if final_destination in destinations:
            raise CourierError(
                f"{context}: destination `{final_destination}` duplicates {destinations[final_destination]}"
            )
        folded = final_destination.casefold()
        if folded in folded_destinations:
            raise CourierError(
                f"{context}: destination `{final_destination}` collides case-insensitively"
                f" with `{folded_destinations[folded]}`"
            )
        destinations[final_destination] = context
        folded_destinations[folded] = final_destination

    for entry in entries:
        context = f"{release_display}:{entry.line_number}"
        if entry.directory:
            members, excluded = _expand_directory(context, content_root, entry, notebook_roots, reserved)
            if tracking is None:
                tracked = _tracked_files(content_root)
                tracking = "verified" if tracked is not None else "skipped"
            for member_source, member_destination in members:
                if tracked is not None and member_source not in tracked:
                    raise CourierError(f"{context}: expanded member is not tracked by Git: `{member_source}`")
                final_destination = _final_destination(public.managed_subtree, member_destination)
                register_destination(context, final_destination)
                exports.append(_planned_export(context, content_root, member_source, final_destination))
            expansions.append(
                DirectoryExpansion(entry=f"{entry.source}/", resolved=len(members), excluded=excluded)
            )
        else:
            final_destination = _final_destination(public.managed_subtree, entry.destination)
            register_destination(context, final_destination)
            if entry.source.endswith(NOTEBOOK_SUFFIX) and _under_root(entry.source, notebook_roots):
                targets.append(_notebook_target(context, content_root, entry.source, final_destination))
            else:
                exports.append(_planned_export(context, content_root, entry.source, final_destination))

    _reject_destination_ancestors(str(release_display), set(destinations))
    return PublicationPlan(
        content_root=content_root,
        public=public,
        exports=tuple(sorted(exports, key=lambda entry: entry.destination)),
        notebook_pairs=(),
        manifest_sha256=sha256(manifest_bytes).hexdigest(),
        version=2,
        release_manifest=release_manifest,
        release_manifest_sha256=sha256(release_bytes).hexdigest(),
        notebook_targets=tuple(sorted(targets, key=lambda target: target.destination)),
        directory_expansions=tuple(sorted(expansions, key=lambda expansion: expansion.entry)),
        expansion_tracking=tracking,
    )


def _parse_release_manifest_field(
    config_path: Path, content_root: Path, manifest: dict[str, object]
) -> tuple[str, Path]:
    value = manifest.get("release_manifest")
    if not isinstance(value, str) or not value:
        raise CourierError(f"{config_path}: `release_manifest` must be a non-empty string")
    parts = _validate_relative_path(config_path, value, "release_manifest")
    _reject_git_component(config_path, parts, "release_manifest")
    _validate_transient_path(config_path, value, parts, "release_manifest")
    current = content_root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise CourierError(f"{config_path}: `release_manifest` contains a symbolic link: `{value}`")
    release_path = content_root.joinpath(*parts)
    if not release_path.is_file():
        raise CourierError(f"{config_path}: `release_manifest` is not a file under the content root: `{value}`")
    return value, release_path


def _parse_notebook_roots(
    config_path: Path, content_root: Path, value: object
) -> tuple[tuple[str, ...], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise CourierError(f"{config_path}: `notebooks` must be a table")
    _reject_unknown_fields(config_path, value, {"jupytext_roots"}, "notebooks")
    raw_roots = value.get("jupytext_roots")
    if (
        not isinstance(raw_roots, list)
        or not raw_roots
        or not all(isinstance(root, str) and root for root in raw_roots)
    ):
        raise CourierError(f"{config_path}: `notebooks.jupytext_roots` must be a non-empty array of strings")
    roots: list[tuple[str, ...]] = []
    for root in raw_roots:
        parts = _validate_relative_path(config_path, root, "notebooks.jupytext_roots")
        _reject_git_component(config_path, parts, "notebooks.jupytext_roots")
        current = content_root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise CourierError(
                    f"{config_path}: `notebooks.jupytext_roots` contains a symbolic link: `{root}`"
                )
        if not content_root.joinpath(*parts).is_dir():
            raise CourierError(
                f"{config_path}: `notebooks.jupytext_roots` is not a directory under the content root: `{root}`"
            )
        for other in roots:
            shorter, longer = sorted([parts, other], key=len)
            if longer[: len(shorter)] == shorter:
                raise CourierError(f"{config_path}: `notebooks.jupytext_roots` entries overlap: `{root}`")
        roots.append(parts)
    return tuple(roots)


def _parse_release_lines(release_display: Path, raw: bytes) -> list[ReleaseEntry]:
    if raw.startswith(codecs.BOM_UTF8):
        raise CourierError(f"{release_display}: release list must not begin with a byte-order mark")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CourierError(f"{release_display}: release list must be UTF-8: {error}") from error

    entries: list[ReleaseEntry] = []
    for number, raw_line in enumerate(text.split("\n"), start=1):
        line = raw_line.rstrip("\r").strip()
        if not line or line.startswith("#"):
            continue
        context = f"{release_display}:{number}"
        if "#" in line:
            raise CourierError(f"{context}: inline comments are not supported: `{line}`")
        if "->" in line:
            if line.count("->") != 1 or ARROW not in line:
                raise CourierError(f"{context}: rename delimiter must be a single ` -> `: `{line}`")
            source, destination = line.split(ARROW, 1)
            if not source or not destination or source != source.rstrip() or destination != destination.lstrip():
                raise CourierError(f"{context}: rename delimiter must be a single ` -> `: `{line}`")
        else:
            source = destination = line
        source_directory = source.endswith("/")
        destination_directory = destination.endswith("/")
        if source_directory != destination_directory:
            raise CourierError(f"{context}: rename must map a file to a file or a directory to a directory: `{line}`")
        if source_directory:
            source = source[:-1]
            destination = destination[:-1]
        source_parts = _validate_relative_path(context, source, "source")
        destination_parts = _validate_relative_path(context, destination, "destination")
        _reject_git_component(context, source_parts, "source")
        _reject_git_component(context, destination_parts, "destination")
        _validate_transient_path(context, source, source_parts, "source")
        entries.append(
            ReleaseEntry(line_number=number, source=source, destination=destination, directory=source_directory)
        )
    return entries


def _reject_duplicate_and_overlapping_entries(
    release_display: Path, entries: list[ReleaseEntry], notebook_roots: tuple[tuple[str, ...], ...]
) -> None:
    seen: dict[str, int] = {}
    for entry in entries:
        if entry.source in seen:
            raise CourierError(
                f"{release_display}:{entry.line_number}: entry duplicates the source on line"
                f" {seen[entry.source]}: `{entry.source}`"
            )
        seen[entry.source] = entry.line_number
    directories = [entry for entry in entries if entry.directory]
    for entry in entries:
        if (
            not entry.directory
            and entry.source.endswith((NOTEBOOK_SUFFIX, MARKDOWN_SUFFIX))
            and _under_root(entry.source, notebook_roots)
        ):
            # Expansion always excludes `.md` and `.ipynb` members beneath a Jupytext root, so an
            # individual listing there is the only way the file publishes and cannot be ambiguous.
            continue
        parts = tuple(entry.source.split("/"))
        for directory in directories:
            directory_parts = tuple(directory.source.split("/"))
            if len(parts) > len(directory_parts) and parts[: len(directory_parts)] == directory_parts:
                later = entry if entry.line_number > directory.line_number else directory
                earlier = directory if later is entry else entry
                raise CourierError(
                    f"{release_display}:{later.line_number}: entry overlaps the entry on line"
                    f" {earlier.line_number}: `{later.source}`"
                )


def _expand_directory(
    context: str,
    content_root: Path,
    entry: ReleaseEntry,
    notebook_roots: tuple[tuple[str, ...], ...],
    reserved: set[str],
) -> tuple[list[tuple[str, str]], int]:
    base_parts = tuple(entry.source.split("/"))
    current = content_root
    for part in base_parts:
        current = current / part
        if current.is_symlink():
            raise CourierError(f"{context}: directory entry contains a symbolic link: `{entry.source}/`")
    base = content_root.joinpath(*base_parts)
    if not base.is_dir():
        raise CourierError(f"{context}: directory entry is not a directory under the content root: `{entry.source}/`")

    members: list[tuple[str, str]] = []
    excluded = 0
    for current_root, directory_names, file_names in os.walk(base, followlinks=False):
        current = Path(current_root)
        directory_names.sort()
        file_names.sort()
        kept: list[str] = []
        for name in directory_names:
            path = current / name
            relative = path.relative_to(content_root).as_posix()
            if name == ".git":
                raise CourierError(f"{context}: directory entry contains a `.git` component: `{relative}`")
            if path.is_symlink():
                raise CourierError(f"{context}: directory entry contains a symbolic link: `{relative}`")
            if name.startswith(".") or name in TRANSIENT_COMPONENTS:
                excluded += 1
                continue
            kept.append(name)
        directory_names[:] = kept
        for name in file_names:
            path = current / name
            relative = path.relative_to(content_root).as_posix()
            if name == ".git":
                raise CourierError(f"{context}: directory entry contains a `.git` component: `{relative}`")
            if path.is_symlink():
                raise CourierError(f"{context}: directory entry contains a symbolic link: `{relative}`")
            if _excluded_member(name, relative, notebook_roots, reserved):
                excluded += 1
                continue
            member_relative = path.relative_to(base).as_posix()
            members.append((relative, f"{entry.destination}/{member_relative}"))
    if not members:
        raise CourierError(f"{context}: directory entry resolves to no publishable files: `{entry.source}/`")
    return members, excluded


def _excluded_member(
    name: str, relative: str, notebook_roots: tuple[tuple[str, ...], ...], reserved: set[str]
) -> bool:
    if name.startswith(".") or name in TRANSIENT_COMPONENTS or name.endswith(TRANSIENT_SUFFIXES):
        return True
    if relative in reserved:
        return True
    if name.endswith((NOTEBOOK_SUFFIX, MARKDOWN_SUFFIX)) and _under_root(relative, notebook_roots):
        return True
    return False


def _under_root(relative: str, notebook_roots: tuple[tuple[str, ...], ...]) -> bool:
    parts = tuple(relative.split("/"))
    return any(parts[: len(root)] == root for root in notebook_roots)


def _tracked_files(content_root: Path) -> set[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(content_root), "ls-files", "-z"], capture_output=True, check=False
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return {name for name in result.stdout.decode("utf-8", "surrogateescape").split("\0") if name}


def _final_destination(managed_subtree: str, destination: str) -> str:
    return destination if managed_subtree == "." else f"{managed_subtree}/{destination}"


def _planned_export(context: str, content_root: Path, source: str, final_destination: str) -> PlannedExport:
    source_path = content_root.joinpath(*source.split("/"))
    _validate_source(context, content_root, source_path, source, "entry")
    return PlannedExport(
        source=source,
        destination=final_destination,
        size_bytes=source_path.stat().st_size,
        sha256=_sha256_file(source_path),
        executable=_is_executable(source_path),
    )


def _notebook_target(context: str, content_root: Path, source: str, final_destination: str) -> NotebookTarget:
    markdown = source[: -len(NOTEBOOK_SUFFIX)] + MARKDOWN_SUFFIX
    markdown_present = _optional_regular_file(context, content_root, markdown)
    notebook_present = _optional_regular_file(context, content_root, source)
    if not markdown_present and not notebook_present:
        raise CourierError(f"{context}: notebook has neither a Markdown source nor a private notebook: `{source}`")
    return NotebookTarget(
        notebook=source,
        destination=final_destination,
        markdown=markdown if markdown_present else None,
        source_present=notebook_present,
    )


def _optional_regular_file(context: str, content_root: Path, relative: str) -> bool:
    current = content_root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise CourierError(f"{context}: `{relative}` contains a symbolic link")
    path = content_root.joinpath(*relative.split("/"))
    if not path.exists():
        return False
    if not path.is_file():
        raise CourierError(f"{context}: `{relative}` is not a regular file")
    try:
        path.resolve(strict=True).relative_to(content_root)
    except ValueError as error:
        raise CourierError(f"{context}: `{relative}` escapes the content root") from error
    return True
