from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from course_courier.cli import app
from course_courier.planner import CourierError
from course_courier.workflow_init import init_workflow, resolve_release_sha

PIN = "a" * 40
WORKFLOW = Path(".github/workflows/course-courier-publish.yml")


def _git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


def make_course(tmp_path: Path, *, content_directory: str | None = "content") -> Path:
    root = tmp_path / "course"
    content = root if content_directory is None else root / content_directory
    content.mkdir(parents=True)
    (content / "one.txt").write_text("one")
    manifest = content / "PUBLISH.toml"
    manifest.write_text(
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
    (content / "RELEASES.txt").write_text("one.txt\n")
    _git(tmp_path, "init", "-q", str(root))
    _git(root, "add", "-A")
    return manifest


def test_scaffolds_the_documented_template(tmp_path: Path) -> None:
    manifest = make_course(tmp_path)

    target = init_workflow(manifest, sha=PIN)

    assert target == (tmp_path / "course" / WORKFLOW).resolve()
    from importlib.metadata import version

    expected = (
        "name: Publish course export\n"
        "\n"
        "on:\n"
        "  push:\n"
        '    branches: ["main"]\n'
        "    paths:\n"
        '      - "content/**"\n'
        "  workflow_dispatch:\n"
        "\n"
        "permissions:\n"
        "  contents: read\n"
        "\n"
        "concurrency:\n"
        '  group: "public-course-publish-insy3010-main"\n'
        "  cancel-in-progress: false\n"
        "\n"
        "jobs:\n"
        "  publish:\n"
        "    environment: public-course-publish\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2\n"
        f"      - uses: olearydj/course-courier/publish@{PIN} # v{version('course-courier')}\n"
        "        with:\n"
        '          config: "content/PUBLISH.toml"\n'
        "          public_token: ${{ secrets.COURSE_COURIER_PUBLIC_TOKEN }}\n"
        "          confirmation: publish\n"
    )
    assert target.read_text() == expected


def test_scaffolds_a_version_1_manifest_and_rejects_invalid_ones(tmp_path: Path) -> None:
    manifest = make_course(tmp_path)
    manifest.write_text(
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
                'source = "one.txt"',
                'destination = "one.txt"',
            ]
        )
    )
    assert init_workflow(manifest, sha=PIN).exists()

    manifest.write_text("version = 3\n")
    with pytest.raises(CourierError, match="version"):
        init_workflow(manifest, sha=PIN, force=True)


def test_rejects_an_invalid_branch_with_the_shared_diagnostic(tmp_path: Path) -> None:
    manifest = make_course(tmp_path)

    with pytest.raises(CourierError, match="`--branch` is not a valid Git branch name"):
        init_workflow(manifest, branch="bad..branch", sha=PIN)
    assert not (tmp_path / "course" / WORKFLOW).exists()


def test_root_content_root_yields_a_bare_star_star_filter(tmp_path: Path) -> None:
    manifest = make_course(tmp_path, content_directory=None)

    target = init_workflow(manifest, sha=PIN)

    document = yaml.safe_load(target.read_text())
    trigger = document.get(True, document.get("on"))
    assert trigger["push"]["paths"] == ["**"]
    assert document["jobs"]["publish"]["steps"][1]["with"]["config"] == "PUBLISH.toml"


def test_yaml_significant_values_round_trip(tmp_path: Path) -> None:
    manifest = make_course(tmp_path, content_directory='course "material"')
    branch = 'topic#quote"branch'

    target = init_workflow(manifest, branch=branch, sha=PIN)

    document = yaml.safe_load(target.read_text())
    trigger = document.get(True, document.get("on"))
    assert trigger["push"]["branches"] == [branch]
    assert trigger["push"]["paths"] == ['course "material"/**']
    assert document["concurrency"]["group"] == f"public-course-publish-insy3010-{branch}"
    assert document["jobs"]["publish"]["steps"][1]["with"]["config"] == 'course "material"/PUBLISH.toml'


def test_rejects_a_manifest_outside_a_work_tree_or_escaping_by_symlink(tmp_path: Path) -> None:
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "one.txt").write_text("one")
    (loose / "RELEASES.txt").write_text("one.txt\n")
    manifest = loose / "PUBLISH.toml"
    manifest.write_text(
        'version = 2\nrelease_manifest = "RELEASES.txt"\n\n[public]\n'
        'repository = "olearydj/INSY3010"\nbranch = "main"\nmanaged_subtree = "course"\n'
    )
    with pytest.raises(CourierError, match="not inside a Git work tree"):
        init_workflow(manifest, sha=PIN)

    inside = make_course(tmp_path)
    try:
        (tmp_path / "course" / "linked").symlink_to(loose)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    # Git resolves the link before locating a work tree, so the escaping manifest is
    # rejected as outside one; the containment check remains as defense-in-depth.
    with pytest.raises(CourierError, match="not inside a Git work tree"):
        init_workflow(tmp_path / "course" / "linked" / "PUBLISH.toml", sha=PIN)
    assert inside.exists()
    assert not (tmp_path / "course" / WORKFLOW).exists()


@pytest.mark.parametrize("link_target", ["root", "content"])
def test_rejects_a_config_symlink_redirecting_into_another_worktree(tmp_path: Path, link_target: str) -> None:
    victim_manifest = make_course(tmp_path)
    victim = tmp_path / "course"
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    _git(tmp_path, "init", "-q", str(attacker))
    link = attacker / "link"
    try:
        link.symlink_to(victim if link_target == "root" else victim / "content")
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    config = link / "content" / "PUBLISH.toml" if link_target == "root" else link / "PUBLISH.toml"

    with pytest.raises(CourierError, match="symbolic link redirecting"):
        init_workflow(config, sha=PIN)

    assert not (victim / WORKFLOW).exists()
    assert not (attacker / WORKFLOW).exists()
    assert init_workflow(victim_manifest, sha=PIN).exists()


@pytest.mark.parametrize("linked", [".github", ".github/workflows"])
def test_rejects_a_symlinked_workflow_parent(tmp_path: Path, linked: str) -> None:
    manifest = make_course(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "course" / Path(linked)
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(CourierError, match="not a symbolic link"):
        init_workflow(manifest, sha=PIN)

    assert list(outside.iterdir()) == []


def test_resolver_returns_the_peeled_commit_not_the_tag_object(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "file.txt").write_text("release")
    _git(tmp_path, "init", "-q", str(upstream))
    _git(upstream, "config", "user.name", "Test")
    _git(upstream, "config", "user.email", "test@example.edu")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", "release")
    _git(upstream, "tag", "-a", "v1.2.3", "-m", "release")
    commit_sha = _git(upstream, "rev-parse", "v1.2.3^{commit}")
    tag_sha = _git(upstream, "rev-parse", "v1.2.3")

    resolved = resolve_release_sha("1.2.3", remote=str(upstream))

    assert resolved == commit_sha
    assert resolved != tag_sha


def test_resolution_failures_name_the_sha_escape_hatch(tmp_path: Path) -> None:
    with pytest.raises(CourierError, match="--sha"):
        resolve_release_sha("1.2.3", remote=str(tmp_path / "missing-remote"))

    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(tmp_path, "init", "-q", str(upstream))
    with pytest.raises(CourierError, match="--sha"):
        resolve_release_sha("0.0.0", remote=str(upstream))

    manifest = make_course(tmp_path)
    with pytest.raises(CourierError, match="40-character"):
        init_workflow(manifest, sha="not-a-sha")
    assert not (tmp_path / "course" / WORKFLOW).exists()


def test_refuses_overwrite_without_force_and_replaces_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = make_course(tmp_path)
    target = tmp_path / "course" / WORKFLOW
    target.parent.mkdir(parents=True)
    target.write_text("prior workflow\n")

    with pytest.raises(CourierError, match="--force"):
        init_workflow(manifest, sha=PIN)
    assert target.read_text() == "prior workflow\n"

    def failing_replace(*arguments: object) -> None:
        raise OSError("interrupted")

    monkeypatch.setattr("course_courier.workflow_init.os.replace", failing_replace)
    with pytest.raises(CourierError, match="could not write"):
        init_workflow(manifest, sha=PIN, force=True)
    assert target.read_text() == "prior workflow\n"
    assert not list(target.parent.glob(f".{target.name}.*"))
    monkeypatch.undo()

    init_workflow(manifest, sha=PIN, force=True)
    assert "olearydj/course-courier/publish@" in target.read_text()


def test_cli_prints_the_path_and_manual_checklist(tmp_path: Path) -> None:
    manifest = make_course(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["init-workflow", "--config", str(manifest), "--sha", PIN])

    assert result.exit_code == 0
    assert str(tmp_path / "course" / WORKFLOW) in result.stdout
    for expectation in ("public-course-publish", "COURSE_COURIER_PUBLIC_TOKEN", "Protect", "workflow_dispatch"):
        assert expectation in result.stdout


def test_setup_guide_contains_no_literal_courier_pin() -> None:
    setup = Path("docs/setup.md").read_text()
    assert not re.search(r"course-courier/publish@[0-9a-f]{40}", setup)
