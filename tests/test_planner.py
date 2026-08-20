from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from typer.testing import CliRunner

from course_courier.cli import app
from course_courier.planner import CourierError, create_plan


def write_manifest(content_root: Path, exports: str, *, public: str | None = None, suffix: str = "") -> Path:
    public = public or 'repository = "olearydj/INSY3010"\nbranch = "main"\nmanaged_subtree = "course"'
    manifest = content_root / "PUBLISH.toml"
    manifest.write_text(f"version = 1\n\n[public]\n{public}\n\n{exports}{suffix}")
    return manifest


def export(source: str, destination: str) -> str:
    return f'[[export]]\nsource = "{source}"\ndestination = "{destination}"\n'


def test_create_plan_is_deterministic_and_does_not_write(tmp_path: Path) -> None:
    (tmp_path / "lectures").mkdir()
    source_a = tmp_path / "lectures" / "a.txt"
    source_b = tmp_path / "lectures" / "b.txt"
    source_a.write_text("alpha\n")
    source_b.write_text("beta\n")
    manifest = write_manifest(tmp_path, export("lectures/b.txt", "z/b.txt") + export("lectures/a.txt", "a/a.txt"))
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    plan = create_plan(manifest)

    assert [entry.destination for entry in plan.exports] == ["course/a/a.txt", "course/z/b.txt"]
    assert plan.exports[0].sha256 == sha256(b"alpha\n").hexdigest()
    assert plan.exports[0].size_bytes == len(b"alpha\n")
    assert plan.manifest_sha256 == sha256(manifest.read_bytes()).hexdigest()
    assert plan.to_json().endswith("\n")
    assert {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("source", ["missing.txt", "directory", "link.txt"])
def test_rejects_missing_directory_and_symlink_sources(tmp_path: Path, source: str) -> None:
    (tmp_path / "directory").mkdir()
    target = tmp_path / "target.txt"
    target.write_text("target")
    try:
        (tmp_path / "link.txt").symlink_to(target)
    except OSError:
        if source == "link.txt":
            pytest.skip("symlinks are unavailable on this platform")
    manifest = write_manifest(tmp_path, export(source, "published.txt"))

    with pytest.raises(CourierError):
        create_plan(manifest)


@pytest.mark.parametrize("value", ["/absolute.txt", "../escape.txt", "a//b.txt", "a\\b.txt", "a/", "."])
def test_rejects_unsafe_paths(tmp_path: Path, value: str) -> None:
    (tmp_path / "safe.txt").write_text("safe")
    manifest = write_manifest(tmp_path, export(value, "published.txt"))

    with pytest.raises(CourierError):
        create_plan(manifest)


@pytest.mark.parametrize("source", [".ipynb_checkpoints/a.ipynb", "__pycache__/a.pyc", ".~draft.md", "draft.tmp"])
def test_rejects_transient_sources(tmp_path: Path, source: str) -> None:
    path = tmp_path.joinpath(*source.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("transient")
    manifest = write_manifest(tmp_path, export(source, "published.txt"))

    with pytest.raises(CourierError, match="transient"):
        create_plan(manifest)


def test_rejects_duplicate_sources_and_destinations(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    (tmp_path / "two.txt").write_text("two")
    duplicate_source = write_manifest(tmp_path, export("one.txt", "one.txt") + export("one.txt", "other.txt"))
    with pytest.raises(CourierError, match="duplicates"):
        create_plan(duplicate_source)

    destination_collision = write_manifest(tmp_path, export("one.txt", "same.txt") + export("two.txt", "same.txt"))
    with pytest.raises(CourierError, match="duplicates"):
        create_plan(destination_collision)


def test_rejects_casefold_and_ancestor_destination_collisions(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    (tmp_path / "two.txt").write_text("two")
    casefold_collision = write_manifest(tmp_path, export("one.txt", "Readme.txt") + export("two.txt", "README.txt"))
    with pytest.raises(CourierError, match="case-insensitively"):
        create_plan(casefold_collision)

    ancestor_collision = write_manifest(tmp_path, export("one.txt", "item") + export("two.txt", "item/child.txt"))
    with pytest.raises(CourierError, match="conflicts"):
        create_plan(ancestor_collision)


def test_managed_root_preserves_destinations_at_the_public_repository_root(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(
        tmp_path,
        export("one.txt", "one.txt"),
        public='repository = "olearydj/INSY7130"\nbranch = "main"\nmanaged_subtree = "."',
    )

    plan = create_plan(manifest)

    assert plan.public.managed_subtree == "."
    assert plan.exports[0].destination == "one.txt"


def test_rejects_schema_errors(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"), suffix="\nunknown = true\n")

    with pytest.raises(CourierError, match="unknown"):
        create_plan(manifest)


def test_manifest_hash_changes_for_comment_only_edit(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"))
    original = create_plan(manifest)
    manifest.write_text(manifest.read_text() + "\n# a comment\n")
    amended = create_plan(manifest)

    assert original.exports == amended.exports
    assert original.manifest_sha256 != amended.manifest_sha256


def test_cli_writes_only_json_on_success_and_no_stdout_on_failure(tmp_path: Path) -> None:
    runner = CliRunner()
    (tmp_path / "one.txt").write_text("one")
    valid = write_manifest(tmp_path, export("one.txt", "one.txt"))
    result = runner.invoke(app, ["plan", "--config", str(valid)])
    assert result.exit_code == 0
    assert result.stdout.endswith("\n")
    assert '"destination":"course/one.txt"' in result.stdout

    invalid = write_manifest(tmp_path, export("missing.txt", "missing.txt"))
    result = runner.invoke(app, ["plan", "--config", str(invalid)])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "does not exist" in result.stderr
