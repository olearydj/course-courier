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

    def as_dict(self) -> dict[str, str | int]:
        result: dict[str, str | int] = {"kind": self.kind}
        if self.size_bytes is not None:
            result["size_bytes"] = self.size_bytes
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        return result


def compare_trees(stage_root: Path, public_root: Path, managed_subtree: str) -> dict[str, object]:
    """Return a deterministic, read-only diff of the configured managed boundary."""
    stage_boundary = _boundary(stage_root, managed_subtree, required=True)
    public_boundary = _boundary(public_root, managed_subtree, required=False)
    staged = _tree_entries(stage_boundary, exclude_git=False)
    public = _tree_entries(public_boundary, exclude_git=managed_subtree == ".") if public_boundary else {}
    added = _render_entries({path: staged[path] for path in staged.keys() - public.keys()})
    removed = _render_entries({path: public[path] for path in public.keys() - staged.keys()})
    changed = _render_changed(staged, public)
    return {
        "changed": bool(added or removed or changed),
        "added": added,
        "removed": removed,
        "changed_entries": changed,
    }


def _boundary(root: Path, managed_subtree: str, *, required: bool) -> Path | None:
    if root.is_symlink() or not root.is_dir():
        raise CourierError(f"{root}: comparison root must be a non-symbolic-link directory")
    boundary = root if managed_subtree == "." else root.joinpath(*managed_subtree.split("/"))
    if boundary.is_symlink():
        raise CourierError(f"{boundary}: managed boundary must not be a symbolic link")
    if boundary.is_dir():
        return boundary
    if required:
        raise CourierError(f"{boundary}: staged managed boundary is missing")
    return None


def _tree_entries(root: Path, *, exclude_git: bool) -> dict[str, TreeEntry]:
    entries: dict[str, TreeEntry] = {}
    for current_root, directories, files in os.walk(root, followlinks=False):
        current = Path(current_root)
        if exclude_git and current == root and ".git" in directories:
            directories.remove(".git")
        for name in directories:
            path = current / name
            relative = path.relative_to(root).as_posix()
            entries[relative] = TreeEntry(kind="symlink" if path.is_symlink() else "directory")
        for name in files:
            path = current / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries[relative] = TreeEntry(kind="symlink")
            else:
                entries[relative] = TreeEntry(kind="file", size_bytes=path.stat().st_size, sha256=_sha256_file(path))
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
