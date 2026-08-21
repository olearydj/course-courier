from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from course_courier.review import compare_trees


def test_compare_root_managed_trees_ignores_git_and_reports_changes(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    public = tmp_path / "public"
    stage.mkdir()
    public.mkdir()
    (stage / "README.md").write_text("new")
    (stage / "added.txt").write_text("added")
    (public / "README.md").write_text("old")
    (public / "removed.txt").write_text("removed")
    (public / ".git").mkdir()
    (public / ".git" / "config").write_text("ignored")

    review = compare_trees(stage, public, ".")

    assert review["changed"] is True
    assert [entry["path"] for entry in review["added"]] == ["added.txt"]
    assert [entry["path"] for entry in review["removed"]] == ["removed.txt"]
    assert [entry["path"] for entry in review["changed_entries"]] == ["README.md"]


def test_compare_non_root_managed_tree_ignores_other_public_files(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    public = tmp_path / "public"
    (stage / "course").mkdir(parents=True)
    public.mkdir()
    (stage / "course" / "lesson.txt").write_text("same")
    (public / "course").mkdir()
    (public / "course" / "lesson.txt").write_text("same")
    (public / "CNAME").write_text("example.edu")

    review = compare_trees(stage, public, "course")

    assert review == {"changed": False, "added": [], "removed": [], "changed_entries": []}


def test_compare_tracks_executable_mode_and_ignores_nested_public_git_repositories(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    public = tmp_path / "public"
    (stage / "course").mkdir(parents=True)
    (public / "course" / "nested" / ".git").mkdir(parents=True)
    staged_file = stage / "course" / "lesson.sh"
    public_file = public / "course" / "lesson.sh"
    staged_file.write_text("#!/bin/sh\nexit 0\n")
    public_file.write_text("#!/bin/sh\nexit 0\n")
    staged_file.chmod(0o755)
    public_file.chmod(0o644)
    (public / "course" / "nested" / ".git" / "config").write_text("ignored")

    review = compare_trees(stage, public, "course")

    assert review["added"] == []
    assert review["removed"] == []
    changed = review["changed_entries"]
    assert changed[0]["path"] == "lesson.sh"
    assert changed[0]["staged"]["executable"] is True
    assert changed[0]["public"]["executable"] is False


def test_compare_ignores_nested_public_git_beside_identical_published_content(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    public = tmp_path / "public"
    (stage / "course" / "nested").mkdir(parents=True)
    (public / "course" / "nested" / ".git").mkdir(parents=True)
    (stage / "course" / "nested" / "data.txt").write_text("same")
    (public / "course" / "nested" / "data.txt").write_text("same")
    (public / "course" / "nested" / ".git" / "config").write_text("manual")

    review = compare_trees(stage, public, "course")

    assert review == {"changed": False, "added": [], "removed": [], "changed_entries": []}


def test_compare_ignores_bare_directories_and_reports_symlinks(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    public = tmp_path / "public"
    (stage / "course").mkdir(parents=True)
    (public / "course" / "empty").mkdir(parents=True)
    (stage / "course" / "lesson.txt").write_text("same")
    (public / "course" / "lesson.txt").write_text("same")
    try:
        (public / "course" / "link.txt").symlink_to(public / "course" / "lesson.txt")
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    review = compare_trees(stage, public, "course")

    assert [entry["path"] for entry in review["added"]] == []
    assert review["removed"] == [{"path": "link.txt", "kind": "symlink"}]
    assert review["changed_entries"] == []


def test_publish_script_reports_review_git_consistency_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    public = workspace / ".course-courier-public"
    stage = tmp_path / "stage"
    output = tmp_path / "output"
    (public / "course").mkdir(parents=True)
    (stage / "course").mkdir(parents=True)
    (public / "course" / "lesson.txt").write_text("old")
    (stage / "course" / "lesson.txt").write_text("new")
    _git(public, "init", "-b", "main")
    _git(public, "config", "user.name", "Test")
    _git(public, "config", "user.email", "test@example.edu")
    _git(public, "add", ".")
    _git(public, "commit", "-m", "initial")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uv", _uv_passthrough())
    _write_executable(fake_bin / "rsync", "#!/usr/bin/env bash\nexit 0\n")
    result = _run_publish_script(
        workspace=workspace,
        stage=stage,
        review=tmp_path / "review.json",
        output=output,
        path=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    )

    assert result.returncode == 1
    assert "review reported a change" in result.stderr
    assert not output.exists()


def test_publish_script_noops_for_a_matching_non_root_tree(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    public = workspace / ".course-courier-public"
    stage = tmp_path / "stage"
    output = tmp_path / "output"
    (public / "course").mkdir(parents=True)
    (stage / "course").mkdir(parents=True)
    (public / "course" / "lesson.txt").write_text("same")
    (stage / "course" / "lesson.txt").write_text("same")
    _initialize_repository(public)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uv", _uv_passthrough())

    result = _run_publish_script(
        workspace=workspace,
        stage=stage,
        review=tmp_path / "review.json",
        output=output,
        path=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    )

    assert result.returncode == 0
    assert output.read_text() == "published=false\n"
    assert _git_output(public, "status", "--porcelain") == ""


def test_publish_script_mirrors_changes_and_preserves_nested_public_git_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    public = workspace / ".course-courier-public"
    stage = tmp_path / "stage"
    output = tmp_path / "output"
    remote = tmp_path / "public.git"
    (public / "course" / "nested" / ".git").mkdir(parents=True)
    (stage / "course").mkdir(parents=True)
    (public / "course" / "lesson.txt").write_text("old")
    (stage / "course" / "lesson.txt").write_text("new lesson")
    (public / "course" / "nested" / ".git" / "config").write_text("manual")
    _initialize_repository(public)
    _git(tmp_path, "init", "--bare", str(remote))
    _git(public, "remote", "add", "origin", str(remote))
    _git(public, "push", "-u", "origin", "main")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uv", _uv_passthrough())

    result = _run_publish_script(
        workspace=workspace,
        stage=stage,
        review=tmp_path / "review.json",
        output=output,
        path=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text() == "published=true\n"
    assert (public / "course" / "lesson.txt").read_text() == "new lesson"
    assert (public / "course" / "nested" / ".git" / "config").read_text() == "manual"
    assert _git_output(public, "status", "--porcelain") == ""


def test_publish_script_creates_a_missing_public_boundary_only_when_publishing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    public = workspace / ".course-courier-public"
    stage = tmp_path / "stage"
    output = tmp_path / "output"
    remote = tmp_path / "public.git"
    public.mkdir(parents=True)
    (stage / "course").mkdir(parents=True)
    (public / "README.md").write_text("outside the managed boundary")
    (stage / "course" / "lesson.txt").write_text("first lesson")
    _initialize_repository(public)
    _git(tmp_path, "init", "--bare", str(remote))
    _git(public, "remote", "add", "origin", str(remote))
    _git(public, "push", "-u", "origin", "main")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uv", _uv_passthrough())

    result = _run_publish_script(
        workspace=workspace,
        stage=stage,
        review=tmp_path / "review.json",
        output=output,
        path=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text() == "published=true\n"
    assert (public / "course" / "lesson.txt").read_text() == "first lesson"
    assert (public / "README.md").read_text() == "outside the managed boundary"
    assert _git_output(public, "status", "--porcelain") == ""


def test_review_scripts_prepare_and_compare_against_a_public_checkout(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    content = workspace / "content"
    public = workspace / ".course-courier-public"
    runner_temp = tmp_path / "runner-temp"
    outputs = tmp_path / "outputs"
    content.mkdir(parents=True)
    (public / "course").mkdir(parents=True)
    runner_temp.mkdir()
    (content / "lesson.txt").write_text("new lesson")
    (public / "course" / "lesson.txt").write_text("old lesson")
    (content / "PUBLISH.toml").write_text(
        "\n".join(
            [
                "version = 1",
                "",
                "[public]",
                'repository = "olearydj/INSY3010"',
                'branch = "main"',
                'managed_subtree = "course"',
                "",
                "[[export]]",
                'source = "lesson.txt"',
                'destination = "lesson.txt"',
            ]
        )
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uv", _uv_passthrough())
    environment = {
        **os.environ,
        "GITHUB_ACTION_PATH": str(Path.cwd()),
        "GITHUB_WORKSPACE": str(workspace),
        "GITHUB_OUTPUT": str(outputs),
        "RUNNER_TEMP": str(runner_temp),
        "CONFIG": "content/PUBLISH.toml",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    prepare = subprocess.run(
        ["bash", "scripts/review-prepare.sh"], check=False, env=environment, capture_output=True, text=True
    )
    assert prepare.returncode == 0, prepare.stderr
    prepared = dict(line.split("=", 1) for line in outputs.read_text().splitlines())
    assert prepared["repository"] == "olearydj/INSY3010"
    assert prepared["branch"] == "main"
    assert prepared["managed_subtree"] == "course"
    assert json.loads(Path(prepared["inventory"]).read_text())["public"]["branch"] == "main"

    environment.update(STAGE=prepared["stage"], REVIEW=prepared["review"], MANAGED_SUBTREE="course")
    compare = subprocess.run(
        ["bash", "scripts/review-compare.sh"], check=False, env=environment, capture_output=True, text=True
    )
    assert compare.returncode == 0, compare.stderr
    assert "changed=true" in outputs.read_text().splitlines()
    review = json.loads(Path(prepared["review"]).read_text())
    assert [entry["path"] for entry in review["changed_entries"]] == ["lesson.txt"]


def test_publish_prepare_script_gates_version_2_digests_together(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    content = workspace / "content"
    content.mkdir(parents=True)
    (content / "lesson.txt").write_text("lesson")
    (content / "RELEASES.txt").write_text("lesson.txt\n")
    (content / "PUBLISH.toml").write_text(
        "\n".join(
            [
                "version = 2",
                'release_manifest = "RELEASES.txt"',
                "",
                "[public]",
                'repository = "olearydj/INSY3010"',
                'branch = "main"',
                'managed_subtree = "course"',
            ]
        )
    )
    manifest_sha256 = hashlib.sha256((content / "PUBLISH.toml").read_bytes()).hexdigest()
    release_sha256 = hashlib.sha256((content / "RELEASES.txt").read_bytes()).hexdigest()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uv", _uv_passthrough())

    lone = _run_prepare_script(
        tmp_path, workspace, "lone", {"EXPECTED_MANIFEST_SHA256": manifest_sha256}, fake_bin
    )
    assert lone.returncode != 0
    assert "together or not at all" in lone.stderr

    both = _run_prepare_script(
        tmp_path,
        workspace,
        "both",
        {
            "EXPECTED_MANIFEST_SHA256": manifest_sha256,
            "EXPECTED_RELEASE_MANIFEST_SHA256": release_sha256,
        },
        fake_bin,
    )
    assert both.returncode == 0, both.stderr
    outputs = dict(
        line.split("=", 1) for line in (tmp_path / "outputs-both").read_text().splitlines() if "=" in line
    )
    assert outputs["release_manifest_sha256"] == release_sha256

    mismatch = _run_prepare_script(
        tmp_path,
        workspace,
        "mismatch",
        {
            "EXPECTED_MANIFEST_SHA256": manifest_sha256,
            "EXPECTED_RELEASE_MANIFEST_SHA256": "0" * 64,
        },
        fake_bin,
    )
    assert mismatch.returncode != 0
    assert "release-list SHA-256 does not match" in mismatch.stderr


def _run_prepare_script(
    tmp_path: Path, workspace: Path, label: str, extra_env: dict[str, str], fake_bin: Path
) -> subprocess.CompletedProcess[str]:
    runner_temp = tmp_path / f"runner-{label}"
    runner_temp.mkdir()
    environment = {
        **os.environ,
        "GITHUB_ACTION_PATH": str(Path("publish").resolve()),
        "GITHUB_WORKSPACE": str(workspace),
        "GITHUB_OUTPUT": str(tmp_path / f"outputs-{label}"),
        "RUNNER_TEMP": str(runner_temp),
        "CONFIG": "content/PUBLISH.toml",
        "PUBLIC_TOKEN": "token",
        "CONFIRMATION": "publish",
        "EXPECTED_MANIFEST_SHA256": "",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        **extra_env,
    }
    return subprocess.run(
        ["bash", "publish/prepare.sh"], check=False, env=environment, capture_output=True, text=True
    )


def _run_publish_script(
    *, workspace: Path, stage: Path, review: Path, output: Path, path: str
) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "GITHUB_ACTION_PATH": str(Path("publish").resolve()),
        "GITHUB_WORKSPACE": str(workspace),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_SHA": "source-sha",
        "STAGE": str(stage),
        "REVIEW": str(review),
        "MANAGED_SUBTREE": "course",
        "MANIFEST_SHA256": "manifest-sha",
        "BRANCH": "main",
        "PATH": path,
    }
    return subprocess.run(
        ["bash", "publish/publish.sh"],
        check=False,
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        text=True,
    )


def _git(directory: Path, *arguments: str) -> None:
    subprocess.run(["git", "-C", str(directory), *arguments], check=True, capture_output=True, text=True)


def _git_output(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *arguments], check=True, capture_output=True, text=True
    ).stdout


def _initialize_repository(directory: Path) -> None:
    _git(directory, "init", "-b", "main")
    _git(directory, "config", "user.name", "Test")
    _git(directory, "config", "user.email", "test@example.edu")
    _git(directory, "add", ".")
    _git(directory, "commit", "-m", "initial")


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents)
    path.chmod(0o755)


def _uv_passthrough() -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "shift",
        "while [ \"$#\" -gt 0 ]; do",
        "  case \"$1\" in",
        "    --locked) shift ;;",
        "    --project) shift 2 ;;",
        "    *) break ;;",
        "  esac",
        "done",
        "if [ \"$1\" = \"python\" ]; then",
        "  shift",
        f"  exec \"{sys.executable}\" \"$@\"",
        "fi",
        "exec \"$@\"",
    ]
    return "\n".join(lines) + "\n"


def test_composite_action_metadata_exposes_review_outputs() -> None:
    import yaml

    action = yaml.safe_load(Path("action.yml").read_text())

    assert action["runs"]["using"] == "composite"
    assert {"config", "public_token"} <= action["inputs"].keys()
    assert {"changed", "inventory_path", "review_path"} <= action["outputs"].keys()
    assert action["runs"]["steps"][0]["with"]["version"] == "0.12.5"
    assert action["runs"]["steps"][0]["uses"].startswith("astral-sh/setup-uv@c771a70e")
    assert all("${{" not in step.get("run", "") for step in action["runs"]["steps"])
    _assert_sha_pinned_steps(action)


def _assert_sha_pinned_steps(action: dict) -> None:
    for step in action["runs"]["steps"]:
        if "uses" not in step:
            continue
        reference = step["uses"].split("@", 1)[1]
        assert len(reference) == 40 and all(character in "0123456789abcdef" for character in reference), step["uses"]


def test_project_declares_its_lockfile_resolution_policy() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())

    assert project["tool"]["uv"]["exclude-newer"] == "3 days"


def test_publish_action_metadata_requires_all_safety_gates() -> None:
    import yaml

    action = yaml.safe_load(Path("publish/action.yml").read_text())

    assert action["runs"]["using"] == "composite"
    assert {
        "config",
        "public_token",
        "expected_manifest_sha256",
        "expected_release_manifest_sha256",
        "confirmation",
    } <= action["inputs"].keys()
    assert action["inputs"]["public_token"]["required"] is True
    assert action["inputs"]["expected_manifest_sha256"]["required"] is False
    assert action["inputs"]["expected_release_manifest_sha256"]["required"] is False
    assert action["runs"]["steps"][0]["with"]["version"] == "0.12.5"
    assert action["runs"]["steps"][0]["uses"].startswith("astral-sh/setup-uv@c771a70e")
    assert all("${{" not in step.get("run", "") for step in action["runs"]["steps"])
    _assert_sha_pinned_steps(action)
    prepare = Path("publish/prepare.sh").read_text()
    assert 'test -n "${PUBLIC_TOKEN}"' in prepare
    assert 'test "${CONFIRMATION}" = "publish"' in prepare
    assert 'inventory["manifest_sha256"] != expected_manifest' in prepare
    assert "EXPECTED_RELEASE_MANIFEST_SHA256" in prepare
    publish = Path("publish/publish.sh").read_text()
    assert "rsync -a --delete --exclude=.git" in publish
    assert "status --porcelain" in publish
    assert "release list ${RELEASE_MANIFEST_SHA256}" in publish
    assert "github.token" not in Path("publish/action.yml").read_text()
