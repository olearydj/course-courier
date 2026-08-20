# Course Courier — Sprint 2 specification

## Purpose

Sprint 2 turns a validated publication plan into a clean, reproducible staged tree and independently verifies that tree. It remains entirely local: it does not synchronize notebooks, clone repositories, call GitHub APIs, create commits, or push public content.

The output of this sprint is `course-courier build` and `course-courier verify`, both consuming the Sprint 1 manifest and planner. The same commands must be suitable for local review and later CI use.

## Prerequisites and scope

Sprint 1's manifest parser and `create_plan` function are authoritative. Sprint 2 must not reimplement or weaken the manifest, path, transient-file, source-link, collision, or managed-boundary validation rules.

Included:

- Clean staging of every file in a validated plan.
- An explicit, safe output-directory contract.
- Preservation of file bytes and executable mode bits where present.
- Independent verification of a staged tree against a newly resolved plan.
- Deterministic inventories suitable for local review and CI artifacts.
- Fixture-based tests for successful staging, tampering, unexpected files, and unsafe output targets.

Excluded:

- Jupytext synchronization, notebook output stripping, or any transformation of source bytes.
- Directory exports in the manifest.
- Git operations, GitHub authentication, Actions, pull requests, commits, or pushes.
- Deleting files from any public repository.

## Terms

- **Plan**: the validated `PublicationPlan` produced by Sprint 1.
- **Staging root**: the local directory that receives the public-tree layout from `build`.
- **Managed boundary**: the directory within a future public repository that Course Courier owns. It is `public.managed_subtree`, or the repository root when the value is `.`.
- **Inventory**: canonical JSON describing a resolved plan or staged tree, including paths, sizes, and SHA-256 hashes.

## CLI

```text
course-courier build  --config content/PUBLISH.toml --output /tmp/course-public
course-courier verify --config content/PUBLISH.toml --output /tmp/course-public
```

Both commands use Typer, accept exactly one required `--config` file and one required `--output` directory path, and return non-zero for invalid arguments or validation failures. `--output` is a filesystem location, not a path stored in the manifest.

## Build contract

`course-courier build` first creates a plan with `create_plan`. If planning fails, it must leave the output path untouched and write no inventory to standard output.

The output path must not exist. This is deliberate: `build` must never delete, empty, merge into, or otherwise alter an existing directory or file. A caller that wants a fresh build chooses a fresh temporary path, such as a runner-provided directory or a new `mktemp` result.

After a successful plan, the builder must:

1. Create a sibling temporary directory of the requested output path.
2. Copy each planned source to its plan destination below that temporary directory. When `managed_subtree = "."`, destinations are directly below the staging root; otherwise they begin with the configured managed subtree.
3. Copy source bytes without content transformation. Preserve the source file's executable mode bits; preserving other metadata is not required.
4. Verify each copied file's SHA-256 hash and size against the plan before making the staged tree visible.
5. Atomically rename the completed temporary directory to the requested output path.
6. Write the canonical staged inventory to standard output, terminated by one newline.

If any build step fails, the builder must remove only the temporary directory it created. It must leave the requested output path absent and the source tree unchanged.

The builder must create parent directories below its temporary staging root as necessary. It must not copy the manifest, unlisted sibling files, empty source directories, symbolic links, hidden metadata, or transient files.

## Staged inventory contract

On success, `build` and `verify` emit identical canonical JSON. It uses the Sprint 1 plan representation, with one additional `output_root` field:

```json
{
  "content_root": "/absolute/path/to/content",
  "exports": [
    {
      "destination": "lectures/01a-course-intro/01a-course-intro.pptx",
      "sha256": "lowercase-hex-digest",
      "size_bytes": 12345,
      "source": "lectures/01a-course-intro/01a-course-intro.pptx"
    }
  ],
  "manifest_sha256": "lowercase-hex-digest",
  "output_root": "/absolute/path/to/course-public",
  "public": {
    "branch": "main",
    "managed_subtree": ".",
    "repository": "olearydj/INSY7130"
  },
  "version": 1
}
```

Object keys are sorted, separators are compact, output is UTF-8, and output ends with exactly one newline. `exports` retains the plan's Unicode-code-point destination ordering. `output_root` is the resolved absolute output path.

## Verify contract

`course-courier verify` must create a fresh plan before inspecting the output path. The output path must exist and be a directory; verify never creates, repairs, modifies, or deletes it.

Verification succeeds only when all of the following are true:

1. Every plan destination exists below the output root as a regular, non-symbolic-link file.
2. Each staged file has the exact plan size and SHA-256 digest.
3. No file, directory, or symbolic link exists under the managed boundary unless it is an ancestor of a planned destination or is itself a planned file.
4. No planned destination resolves outside the output root.
5. The output root contains no unexpected entries when `managed_subtree = "."`.

For a non-root managed subtree, entries outside that subtree are ignored by verification; later Git mirroring must likewise avoid them. Verification should report all discovered discrepancies in one diagnostic where practical, but may stop on an unrecoverable filesystem error.

Successful verification emits the staged inventory described above. Failure exits non-zero, writes a concise diagnostic to standard error, and writes no inventory to standard output.

## Implementation boundary

The library exposes functions equivalent to:

```python
def build(config_path: Path, output_path: Path) -> StagedInventory:
    """Create a new staged tree from a validated plan."""


def verify(config_path: Path, output_path: Path) -> StagedInventory:
    """Validate an existing staged tree against a newly resolved plan."""
```

The CLI is a thin Typer adapter. Both functions call `create_plan` and return data that serializes through one canonical-inventory implementation. They must not call Jupytext, Git, GitHub, or network services.

## Acceptance tests

Tests use temporary fixture course trees and cover the library and CLI. At minimum, they prove the following:

1. Building a valid plan creates a new output tree with precisely the listed files, expected bytes, expected modes, and expected inventory.
2. The source tree is unchanged after a successful build and after a failed build.
3. Build rejects output paths that already exist as a file, empty directory, or non-empty directory without modifying them.
4. A failed copy or validation leaves no requested output directory and cleans up only its builder-created temporary directory.
5. Verification succeeds for an untouched build and emits the same inventory as build, except for the independently recomputed result object.
6. Verification rejects a missing file, changed file content, changed file size, symbolic-link substitution, an unexpected file, and an unexpected empty directory within the managed boundary.
7. For a non-root managed subtree, verification permits independently maintained entries outside that subtree and rejects unexpected entries inside it.
8. For `managed_subtree = "."`, verification rejects every unexpected entry below the output root, including a `.github/` directory.
9. Build and verify errors have non-zero status, useful standard-error diagnostics, and empty standard output.
10. Canonical inventories retain destination ordering and change when the manifest or a staged file changes.

## Definition of done

Sprint 2 is complete when `build` and `verify` meet this specification, their full fixture suite passes, and a manually reviewed INSY7130 build produces exactly the six-file public tree currently described by `content/PUBLISH.toml`. No notebook transformation or GitHub publication is required for Sprint 2 completion.
