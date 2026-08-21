"""Read-only comparison of a staged managed tree and a public repository tree."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .planner import CourierError


@dataclass(frozen=True)
class TreeEntry:
    kind: str
    size_bytes: int | None = None
    sha256: str | None = None
    executable: bool | None = None

    def as_dict(self) -> dict[str, str | int | bool]:
        result: dict[str, str | int | bool] = {"kind": self.kind}
        if self.size_bytes is not None:
            result["size_bytes"] = self.size_bytes
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        if self.executable is not None:
            result["executable"] = self.executable
        return result


def compare_trees(stage_root: Path, public_root: Path, managed_subtree: str) -> dict[str, object]:
    """Return a deterministic, read-only diff of the configured managed boundary."""
    stage_boundary = _boundary(stage_root, managed_subtree)
    public_boundary = _boundary(public_root, managed_subtree)
    if stage_boundary is None:
        raise CourierError(f"{stage_root}: staged managed boundary is missing")
    staged = _tree_entries(stage_boundary)
    public = _tree_entries(public_boundary) if public_boundary is not None else {}
    added = _render_entries({path: staged[path] for path in staged.keys() - public.keys()})
    removed = _render_entries({path: public[path] for path in public.keys() - staged.keys()})
    changed = _render_changed(staged, public)
    return {
        "changed": bool(added or removed or changed),
        "added": added,
        "removed": removed,
        "changed_entries": changed,
    }


def _boundary(root: Path, managed_subtree: str) -> Path | None:
    if root.is_symlink() or not root.is_dir():
        raise CourierError(f"{root}: comparison root must be a non-symbolic-link directory")
    boundary = root if managed_subtree == "." else root.joinpath(*managed_subtree.split("/"))
    if boundary.is_symlink():
        raise CourierError(f"{boundary}: managed boundary must not be a symbolic link")
    return boundary if boundary.is_dir() else None


def _tree_entries(root: Path) -> dict[str, TreeEntry]:
    """Return the Git-representable entries of a tree: regular files and symbolic links.

    `.git` entries are excluded at every depth on both sides, mirroring the publisher's rsync
    exclusion. Bare directories are not entries: Git cannot represent an empty directory, so a
    directory-only difference could never produce a publishable change and would only wedge the
    review-changed-but-Git-clean consistency check.
    """
    entries: dict[str, TreeEntry] = {}
    for current_root, directories, files in os.walk(root, followlinks=False):
        current = Path(current_root)
        if ".git" in directories:
            directories.remove(".git")
        for name in directories:
            path = current / name
            if path.is_symlink():
                entries[path.relative_to(root).as_posix()] = TreeEntry(kind="symlink")
        for name in files:
            if name == ".git":
                continue
            path = current / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries[relative] = TreeEntry(kind="symlink")
            else:
                details = path.stat()
                entries[relative] = TreeEntry(
                    kind="file",
                    size_bytes=details.st_size,
                    sha256=_sha256_file(path),
                    executable=bool(details.st_mode & 0o111),
                )
    return entries


def _render_entries(entries: dict[str, TreeEntry]) -> list[dict[str, object]]:
    return [{"path": path, **entry.as_dict()} for path, entry in sorted(entries.items())]


def _render_changed(staged: dict[str, TreeEntry], public: dict[str, TreeEntry]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for path in sorted(staged.keys() & public.keys()):
        if staged[path] != public[path]:
            results.append({"path": path, "staged": staged[path].as_dict(), "public": public[path].as_dict()})
    return results


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a staged Course Courier tree with a public checkout.")
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--public", required=True, type=Path)
    parser.add_argument("--managed-subtree", required=True)
    arguments = parser.parse_args()
    review = compare_trees(arguments.stage, arguments.public, arguments.managed_subtree)
    print(json.dumps(review, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
