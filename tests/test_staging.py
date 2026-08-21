from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from course_courier.cli import app
from course_courier.planner import CourierError
from course_courier.staging import build, verify


def write_manifest(content_root: Path, exports: str, *, managed_subtree: str = "course") -> Path:
    manifest = content_root / "PUBLISH.toml"
    manifest.write_text(
        "\n".join(
            [
                "version = 1",
                "",
                "[public]",
                'repository = "olearydj/INSY3010"',
                'branch = "main"',
                f'managed_subtree = "{managed_subtree}"',
                "",
                exports,
            ]
        )
    )
    return manifest


def export(source: str, destination: str) -> str:
    return f'[[export]]\nsource = "{source}"\ndestination = "{destination}"\n'


def test_build_and_verify_create_a_precise_staged_tree(tmp_path: Path) -> None:
    source = tmp_path / "lectures" / "run.sh"
    source.parent.mkdir()
    source.write_text("#!/bin/sh\necho course\n")
    source.chmod(source.stat().st_mode | stat.S_IXUSR)
    manifest = write_manifest(tmp_path, export("lectures/run.sh", "unit/run.sh"))
    output = tmp_path / "staged"

    inventory = build(manifest, output)
    staged = output / "course" / "unit" / "run.sh"

    assert staged.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(staged.stat().st_mode) == 0o755
    assert json.loads(inventory.to_json())["exports"][0]["executable"] is True
    assert inventory.output_root == output.resolve()
    assert verify(manifest, output).to_json() == inventory.to_json()
    assert json.loads(inventory.to_json())["output_root"] == str(output.resolve())


@pytest.mark.parametrize("existing", ["file", "directory"])
def test_build_refuses_existing_output_without_modifying_it(tmp_path: Path, existing: str) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"))
    output = tmp_path / "staged"
    if existing == "file":
        output.write_text("keep")
    else:
        output.mkdir()
        (output / "keep.txt").write_text("keep")

    with pytest.raises(CourierError, match="must not already exist"):
        build(manifest, output)

    if existing == "file":
        assert output.read_text() == "keep"
    else:
        assert (output / "keep.txt").read_text() == "keep"


def test_build_failure_leaves_no_requested_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"))
    output = tmp_path / "staged"

    def fail_copy(*args: object) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr("course_courier.staging._copy_export", fail_copy)

    with pytest.raises(CourierError, match="could not build"):
        build(manifest, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".staged.*"))
    assert (tmp_path / "one.txt").read_text() == "one"


def test_build_verifies_before_renaming_the_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "one.txt"
    source.write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"))
    output = tmp_path / "staged"

    def fail_verify(*args: object) -> None:
        raise CourierError("verification failed")

    monkeypatch.setattr("course_courier.staging._verify_tree", fail_verify)

    with pytest.raises(CourierError, match="verification failed"):
        build(manifest, output)

    assert not output.exists()
    assert source.read_text() == "one"


@pytest.mark.parametrize("tamper", ["missing", "contents", "directory", "symlink", "executable"])
def test_verify_rejects_tampered_staged_files(tmp_path: Path, tamper: str) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"))
    output = tmp_path / "staged"
    build(manifest, output)
    staged = output / "course" / "one.txt"
    if tamper == "missing":
        staged.unlink()
    elif tamper == "contents":
        staged.write_text("changed")
    elif tamper == "directory":
        staged.unlink()
        staged.mkdir()
    elif tamper == "executable":
        staged.chmod(0o755)
    else:
        staged.unlink()
        try:
            staged.symlink_to(tmp_path / "one.txt")
        except OSError:
            pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(CourierError, match="does not match plan"):
        verify(manifest, output)


def test_staging_normalizes_any_source_execute_bit_to_git_mode(tmp_path: Path) -> None:
    source = tmp_path / "owner-only.sh"
    source.write_text("#!/bin/sh\nexit 0\n")
    source.chmod(0o700)
    manifest = write_manifest(tmp_path, export("owner-only.sh", "owner-only.sh"))
    output = tmp_path / "staged"

    build(manifest, output)

    staged = output / "course" / "owner-only.sh"
    assert stat.S_IMODE(staged.stat().st_mode) == 0o755
    assert verify(manifest, output)


def test_verify_rejects_unexpected_file_and_directory_inside_boundary(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"))
    output = tmp_path / "staged"
    build(manifest, output)
    (output / "course" / "extra.txt").write_text("unexpected")
    (output / "course" / "empty").mkdir()

    with pytest.raises(CourierError, match="unexpected"):
        verify(manifest, output)


def test_verify_ignores_entries_outside_a_non_root_boundary(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"))
    output = tmp_path / "staged"
    build(manifest, output)
    (output / "CNAME").write_text("example.edu")

    verify(manifest, output)


def test_root_managed_output_rejects_all_unexpected_entries(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"), managed_subtree=".")
    output = tmp_path / "staged"
    build(manifest, output)
    (output / ".github").mkdir()

    with pytest.raises(CourierError, match="unexpected directory"):
        verify(manifest, output)


def test_cli_build_and_verify_emit_inventory_and_fail_without_stdout(tmp_path: Path) -> None:
    runner = CliRunner()
    (tmp_path / "one.txt").write_text("one")
    manifest = write_manifest(tmp_path, export("one.txt", "one.txt"))
    output = tmp_path / "staged"

    build_result = runner.invoke(app, ["build", "--config", str(manifest), "--output", str(output)])
    assert build_result.exit_code == 0
    assert json.loads(build_result.stdout)["output_root"] == str(output.resolve())

    verify_result = runner.invoke(app, ["verify", "--config", str(manifest), "--output", str(output)])
    assert verify_result.exit_code == 0
    assert verify_result.stdout == build_result.stdout

    output.joinpath("course", "unexpected.txt").write_text("unexpected")
    failed_result = runner.invoke(app, ["verify", "--config", str(manifest), "--output", str(output)])
    assert failed_result.exit_code == 2
    assert failed_result.stdout == ""
    assert "unexpected" in failed_result.stderr
