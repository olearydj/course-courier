from __future__ import annotations

import tomllib
from pathlib import Path

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


def test_composite_action_metadata_exposes_review_outputs() -> None:
    import yaml

    action = yaml.safe_load(Path("action.yml").read_text())

    assert action["runs"]["using"] == "composite"
    assert {"config", "public_token"} <= action["inputs"].keys()
    assert {"changed", "inventory_path", "review_path"} <= action["outputs"].keys()
    assert action["runs"]["steps"][0]["with"]["version"] == "0.12.5"


def test_project_declares_its_lockfile_resolution_policy() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())

    assert project["tool"]["uv"]["exclude-newer"] == "3 days"


def test_publish_action_metadata_requires_all_safety_gates() -> None:
    import yaml

    action = yaml.safe_load(Path("publish/action.yml").read_text())
    prepare = action["runs"]["steps"][1]

    assert action["runs"]["using"] == "composite"
    assert {"config", "public_token", "expected_manifest_sha256", "confirmation"} <= action["inputs"].keys()
    assert action["inputs"]["public_token"]["required"] is True
    assert action["runs"]["steps"][0]["with"]["version"] == "0.12.5"
    assert 'test "${CONFIRMATION}" = "publish"' in prepare["run"]
    assert "reviewed manifest SHA-256 does not match the current manifest" in prepare["run"]
    publish = action["runs"]["steps"][3]["run"]
    assert "rsync -a --delete --exclude=.git" in publish
    assert "github.token" not in Path("publish/action.yml").read_text()
