# Course Courier — Sprint 1 specification

## Purpose

Sprint 1 establishes the trusted core of Course Courier: resolve an explicit publication manifest into a deterministic, safe export plan. It does not copy files, modify a public repository, or implement GitHub Actions.

The output of this sprint is a Python CLI and library with enough tested behaviour for later sprints to build a staged export safely.

## Implementation tooling

The project requires Python 3.11 or later and is managed with [uv](https://docs.astral.sh/uv/). Contributors create the development environment and run checks with `uv sync --group dev`, `uv run pytest`, and `uv run ruff check .`. The repository commits `pyproject.toml` and `uv.lock`; `.venv/` is local and untracked.

Typer is the only runtime dependency in Sprint 1 and owns CLI declaration, option parsing, help text, and exit handling. uv's `uv_build` backend packages the project. TOML parsing (`tomllib`), path handling, hashing, JSON serialization, and data models use the Python standard library. Development dependencies are pytest for tests and Ruff for linting and formatting.

## Scope

Included:

- TOML manifest parsing and schema validation.
- Resolution of manifest entries against a configured course `content/` root.
- Strict source and destination path validation.
- Detection of invalid, duplicate, or colliding exports.
- A deterministic, machine-readable publication inventory.
- The `course-courier plan` command and fixture-based tests.

Excluded:

- Copying files or creating output directories (`build`).
- Verifying staged output (`verify`).
- Jupytext synchronization and notebook output stripping.
- Directory exports.
- GitHub Actions, cloning, commits, pull requests, and pushing.

## Terms

- **Content root**: the local directory containing a course's publishable artifacts and manifest. It is supplied to the CLI through the manifest path; the parent directory of that file is the content root in Sprint 1.
- **Source**: a file under the content root named by an `[[export]]` entry.
- **Destination**: the relative path the source will have inside the managed public subtree.
- **Plan**: the complete, validated, ordered list of source-to-destination mappings. A plan makes no filesystem changes.
- **Managed subtree**: a configurable directory in the public repository that Course Courier exclusively owns. It is normally a non-empty directory; `.` explicitly means the public repository root is wholly managed. Later mirroring may delete only within this boundary.

## Manifest schema

The initial manifest format is TOML version 1.

```toml
version = 1

[public]
repository = "olearydj/INSY3010"
branch = "main"
managed_subtree = "course"

[[export]]
source = "lectures/01a-course-introduction/01a-course-introduction.pptx"
destination = "lectures/01a-course-introduction/01a-course-introduction.pptx"
```

### Top-level fields

| Field | Required | Rules |
| --- | --- | --- |
| `version` | yes | Integer. Sprint 1 accepts exactly `1`. |
| `public` | yes | Table containing the public-target settings below. |
| `export` | yes | One or more array-table entries. |

Unknown top-level fields and unknown fields within known tables are errors.

### `[public]` fields

| Field | Required | Rules |
| --- | --- | --- |
| `repository` | yes | Non-empty GitHub `owner/repository` identifier; exactly one `/`; neither segment is empty. |
| `branch` | yes | A valid Git branch name. It cannot use Git's reserved or forbidden ref syntax. |
| `managed_subtree` | yes | A safe relative directory path without `..` segments, or exactly `.` to manage the entire public repository. |

### `[[export]]` fields

| Field | Required | Rules |
| --- | --- | --- |
| `source` | yes | A safe relative path to one regular file under the content root. |
| `destination` | yes | A safe relative path below `managed_subtree`; it denotes a file, not a directory. |

Every source and destination is interpreted with POSIX-style `/` separators, even when Course Courier runs on another platform. Empty values, absolute paths, `.` paths, `..` segments, repeated separators, backslashes, trailing slashes, and `.git` path components are invalid. A path segment must not be empty.

`public.managed_subtree` alone may be `.`. This declares that Course Courier owns the public repository root and that a future mirror may delete any public-repository file not named in the manifest. It must be chosen only when the public repository has no independently maintained files such as a `CNAME` or `.github/` workflow.

The manifest is itself private configuration: adding `PUBLISH.toml` to an export list is allowed only if it is below the content root and passes the ordinary source rules. Courses should normally not publish it.

## Safety and validation rules

Validation happens before any plan is emitted. A manifest is invalid if any of the following applies:

1. Its schema or supported version is invalid.
2. A source does not exist, is not a regular file, or is a symbolic link.
3. Resolving a source escapes the real content root.
4. A source path contains a disallowed transient component: `.ipynb_checkpoints`, `__pycache__`, `.DS_Store`, or a component beginning `.~`.
5. A source has one of these transient final names: `.DS_Store`, or a name ending in `~`, `.tmp`, or `.swp`.
6. Two entries name the same source. Explicit duplication is rejected even if their destinations differ.
7. Two entries resolve to the same destination.
8. One destination is an ancestor of another destination. Although files cannot be directory ancestors in a final tree, rejecting this early makes future directory-export behaviour unambiguous.

The implementation must use path-aware operations, never string-prefix tests, to establish containment. It rejects destinations that collide when compared case-insensitively on every platform, ensuring a manifest is portable between maintainer filesystems. Sources retain the filesystem's native case semantics.

Sprint 1 does not follow symbolic links. This is intentionally stricter than the eventual policy proposed in the README and prevents uncertainty about what would be published. Supporting internal links, if needed, is a future explicit feature with dedicated tests.

## Plan contract

`course-courier plan --config content/PUBLISH.toml` resolves the manifest and writes one plan to standard output. It must not write files, create directories, or alter the source tree.

The default output is canonical JSON, encoded as UTF-8 and terminated by a single newline:

```json
{
  "version": 1,
  "content_root": "/absolute/path/to/content",
  "public": {
    "repository": "olearydj/INSY3010",
    "branch": "main",
    "managed_subtree": "course"
  },
  "exports": [
    {
      "source": "lectures/01a-course-introduction/01a-course-introduction.pptx",
      "destination": "course/lectures/01a-course-introduction/01a-course-introduction.pptx",
      "size_bytes": 12345,
      "sha256": "lowercase-hex-digest",
      "executable": false
    }
  ],
  "manifest_sha256": "lowercase-hex-digest"
}
```

`exports` is sorted lexicographically by final destination using Unicode code point ordering. `destination` includes `managed_subtree`; this makes the future mirror target explicit. `source` remains relative to the content root. File digests are SHA-256 hashes of source bytes. `executable` is true when any source execute permission bit is set. `manifest_sha256` is the SHA-256 hash of the raw manifest bytes, not a re-serialized TOML value.

Canonical JSON uses sorted object keys, compact separators, and no formatting indentation. A later `--format text` option may present the same information for people, but is not in Sprint 1.

On a validation error the command exits non-zero, writes a concise diagnostic to standard error, and writes no plan to standard output. Diagnostics must name the configuration path and, where applicable, the export entry number and bad path. Internal stack traces appear only with an explicit debug option, which is not required in Sprint 1.

## CLI and library boundary

The package exposes a library function equivalent to:

```python
def create_plan(config_path: Path) -> PublicationPlan:
    """Parse, validate, and resolve a manifest without writing files."""
```

The CLI is implemented with Typer and is a thin adapter around this function. It must be possible for future `build` and `verify` commands to consume the returned plan without reparsing or weakening validation.

`course-courier --help` and `course-courier plan --help` must be available. Unknown commands and unknown command options exit non-zero.

## Acceptance tests

Tests use fixture course trees and invoke both the library and CLI. At minimum, they prove the following:

1. A valid manifest produces the expected canonical plan, ordered by final destination, with correct source hashes, manifest hash, and sizes.
2. Planning leaves a snapshot of the fixture tree unchanged.
3. Missing source, directory source, and symbolic-link source are rejected.
4. Absolute paths, traversal, backslashes, empty paths, trailing slashes, and malformed `managed_subtree` values are rejected.
5. Sources outside the content root and all listed transient-path cases are rejected.
6. Duplicate sources, exact destination collisions, and destination ancestor collisions are rejected.
7. Unsupported manifest versions, missing required values, wrong TOML types, and unknown fields are rejected.
8. A validation failure has non-zero status, a useful standard-error message, and empty standard output.
9. Changing only a manifest comment changes `manifest_sha256` but not the resolved exports; changing a source file changes that export's hash and size as applicable.

Tests must construct a symlink only when the platform supports it; otherwise that single case may be conditionally skipped with an explicit reason.

## Definition of done

Sprint 1 is complete when the CLI and library meet this specification, all acceptance tests pass locally, and the README's proposed interface accurately describes the implemented `plan` command. No build, verify, or GitHub Action work is necessary for completion.
