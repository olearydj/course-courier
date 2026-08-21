"""Scaffold a course repository's publish workflow with immutable action pins."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from importlib import metadata
from pathlib import Path

import yaml

from .planner import CourierError, _validate_branch, create_plan

OFFICIAL_REMOTE = "https://github.com/olearydj/course-courier.git"
CHECKOUT_PIN = "11bd71901bbe5b1630ceea73d27597364c9af683"
CHECKOUT_VERSION = "v4.2.2"
WORKFLOW_RELATIVE_PATH = Path(".github") / "workflows" / "course-courier-publish.yml"
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

MANUAL_CHECKLIST = (
    "Remaining manual steps:",
    "  1. Create the `public-course-publish` Environment on this repository,"
    " restricted to the publishing branch.",
    "  2. Add a fine-grained token scoped to the public repository as the"
    " environment secret `COURSE_COURIER_PUBLIC_TOKEN`.",
    "  3. Protect the publishing branch.",
    "  4. Run the workflow once by hand (workflow_dispatch) and inspect its"
    " artifact before relying on pushes.",
)


def init_workflow(
    config_path: Path,
    *,
    branch: str = "main",
    sha: str | None = None,
    force: bool = False,
    remote: str = OFFICIAL_REMOTE,
) -> Path:
    """Write the pinned publish workflow at the work-tree root and return its path."""
    config_path = Path(config_path)
    plan = create_plan(config_path)
    _validate_branch(config_path, branch, "--branch")

    worktree = _worktree_root(config_path)
    try:
        config_relative = config_path.resolve().relative_to(worktree).as_posix()
        content_relative = plan.content_root.relative_to(worktree).as_posix()
    except ValueError as error:
        raise CourierError(
            f"{config_path}: manifest and content root must lie beneath the Git work-tree root {worktree}"
        ) from error

    if sha is not None:
        publish_pin = _require_commit_sha(sha, "--sha")
    else:
        publish_pin = resolve_release_sha(_package_version(), remote=remote)

    paths_filter = "**" if content_relative == "." else f"{content_relative}/**"
    repository_segment = plan.public.repository.split("/")[1].lower()
    concurrency_group = f"public-course-publish-{repository_segment}-{branch}"
    version = _package_version()

    rendered = _render_workflow(
        branch=branch,
        paths_filter=paths_filter,
        concurrency_group=concurrency_group,
        publish_pin=publish_pin,
        version=version,
        config_relative=config_relative,
    )
    _validate_rendered(
        rendered,
        branch=branch,
        paths_filter=paths_filter,
        concurrency_group=concurrency_group,
        publish_pin=publish_pin,
        config_relative=config_relative,
    )

    target = worktree / WORKFLOW_RELATIVE_PATH
    if target.exists() and not force:
        raise CourierError(f"{target}: workflow already exists; pass --force to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, rendered)
    return target


def resolve_release_sha(version: str, *, remote: str = OFFICIAL_REMOTE) -> str:
    """Resolve the peeled commit SHA of this release's annotated tag on the official remote."""
    tag = f"v{version}"
    reference = f"refs/tags/{tag}^{{}}"
    try:
        result = subprocess.run(
            ["git", "ls-remote", remote, reference], capture_output=True, text=True, check=False, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CourierError(f"cannot resolve release tag {tag}: {error}; pass --sha with a reviewed commit") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or "git ls-remote failed"
        raise CourierError(f"cannot resolve release tag {tag}: {detail}; pass --sha with a reviewed commit")
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == reference:
            return _require_commit_sha(fields[0], reference)
    raise CourierError(
        f"no release tag {tag} on {remote}; this build may be unreleased - pass --sha with a reviewed commit"
    )


def _package_version() -> str:
    return metadata.version("course-courier")


def _worktree_root(config_path: Path) -> Path:
    directory = config_path.resolve().parent
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise CourierError(f"{config_path}: cannot locate a Git work tree: {error}") from error
    if result.returncode != 0:
        raise CourierError(f"{config_path}: the manifest is not inside a Git work tree")
    return Path(result.stdout.strip()).resolve()


def _require_commit_sha(value: str, label: str) -> str:
    if not COMMIT_SHA_PATTERN.fullmatch(value):
        raise CourierError(f"`{label}` must be a 40-character hexadecimal commit SHA, not `{value}`")
    return value


def _yaml_quote(value: str) -> str:
    # A JSON string is a valid YAML double-quoted scalar, so this round-trips any
    # branch or path value that survives the shared validation rules.
    return json.dumps(value, ensure_ascii=False)


def _render_workflow(
    *,
    branch: str,
    paths_filter: str,
    concurrency_group: str,
    publish_pin: str,
    version: str,
    config_relative: str,
) -> str:
    return (
        "name: Publish course export\n"
        "\n"
        "on:\n"
        "  push:\n"
        f"    branches: [{_yaml_quote(branch)}]\n"
        "    paths:\n"
        f"      - {_yaml_quote(paths_filter)}\n"
        "  workflow_dispatch:\n"
        "\n"
        "permissions:\n"
        "  contents: read\n"
        "\n"
        "concurrency:\n"
        f"  group: {_yaml_quote(concurrency_group)}\n"
        "  cancel-in-progress: false\n"
        "\n"
        "jobs:\n"
        "  publish:\n"
        "    environment: public-course-publish\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - uses: actions/checkout@{CHECKOUT_PIN} # {CHECKOUT_VERSION}\n"
        f"      - uses: olearydj/course-courier/publish@{publish_pin} # v{version}\n"
        "        with:\n"
        f"          config: {_yaml_quote(config_relative)}\n"
        "          public_token: ${{ secrets.COURSE_COURIER_PUBLIC_TOKEN }}\n"
        "          confirmation: publish\n"
    )


def _validate_rendered(
    rendered: str,
    *,
    branch: str,
    paths_filter: str,
    concurrency_group: str,
    publish_pin: str,
    config_relative: str,
) -> None:
    try:
        document = yaml.safe_load(rendered)
    except yaml.YAMLError as error:
        raise CourierError(f"rendered workflow is not valid YAML: {error}") from error
    trigger = document[True] if True in document else document["on"]
    publish_step = document["jobs"]["publish"]["steps"][1]
    intended = [
        (trigger["push"]["branches"], [branch]),
        (trigger["push"]["paths"], [paths_filter]),
        (document["concurrency"]["group"], concurrency_group),
        (publish_step["uses"].split(" ")[0], f"olearydj/course-courier/publish@{publish_pin}"),
        (publish_step["with"]["config"], config_relative),
    ]
    for actual, expected in intended:
        if actual != expected:
            raise CourierError(f"rendered workflow did not round-trip: {actual!r} != {expected!r}")


def _atomic_write(target: Path, contents: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
        os.replace(temporary, target)
    except OSError as error:
        raise CourierError(f"{target}: could not write workflow: {error.strerror or error}") from error
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
