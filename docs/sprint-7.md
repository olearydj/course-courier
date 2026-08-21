# Course Courier — Sprint 7 specification

## Purpose

Sprint 7 makes release selection pleasant to author without weakening the explicit, bounded publication model established in Sprints 1 through 6 and hardened in Sprint 6.5. `RELEASES.txt` becomes the normal course-maintainer interface for selecting public material. `PUBLISH.toml` remains, but only for publication policy and the few behaviours that cannot safely be inferred from a list of paths.

This is an additive manifest version: existing version-1 `PUBLISH.toml` files remain valid and retain their current behaviour until a course deliberately adopts `RELEASES.txt`. Sprint 7 builds on Sprint 6.5's shared validation: Git branch-name rules, `.git` path-component rejection, executable-bit comparison, and semantic notebook comparison apply to every path and comparison this sprint introduces.

## Configuration model

An adopting course keeps a compact `content/PUBLISH.toml` containing its public destination, branch, managed subtree, and a reference to the release list. A version-2 manifest contains no `[[export]]` or `[[notebook]]` tables; both are unknown-field errors in version 2, exactly as `release_manifest` and `[notebooks]` remain unknown-field errors in version 1.

```toml
version = 2
release_manifest = "RELEASES.txt"

[public]
repository = "olearydj/INSY3010"
branch = "main"
managed_subtree = "."

[notebooks]
jupytext_roots = ["lectures"]
```

`release_manifest` is a required safe relative path under the content root, validated by the same path rules as any source, resolving to an existing regular non-symbolic-link file. Because it must live under the content root, the existing `content/**` workflow trigger set already covers it. Like `PUBLISH.toml`, the release list is private configuration: it is published only if explicitly listed, and courses normally should not list it.

`[notebooks]` is optional. `jupytext_roots` is a non-empty array of safe relative directory paths under the content root. Each root must exist as a directory, no root may be `.`, and no root may equal, contain, or be contained by another root. Unknown fields in `[notebooks]` are errors.

## Release list format

`RELEASES.txt` is UTF-8 plain text without a byte-order mark; a leading BOM is an error. Lines end with LF or CRLF; a trailing carriage return is stripped, and each line's leading and trailing whitespace is stripped before interpretation.

A blank line is ignored. A line whose first non-whitespace character is `#` is a comment. Inline comments are not supported: an entry containing `#` anywhere is an error, with a diagnostic stating that inline comments are unsupported. Every other line is an allowlisted entry relative to the configured content root.

```text
# Course-wide material
LICENSE
README.md

# Student-facing lectures
lectures/01a-course-introduction/01a-course-introduction.pptx
lectures/01b-operators-and-expressions/01b-operators-and-expressions.ipynb
```

An ordinary path publishes that file at the same relative destination. A path with a trailing slash publishes a directory recursively at the same relative destination, under the expansion rules below.

The format provides one escape hatch for the uncommon renamed export: `source -> destination`. The delimiter is the literal sequence space, `->`, space, occurring exactly once in the line; a line containing more than one `->`, an empty side, or an unspaced arrow is an error. Both sides of a rename must be the same shape: file to file, or directory to directory with a trailing slash on both sides; mixed shapes are errors. A line without `->` is always an identity mapping.

Every source and destination, on either side of an arrow and for every file resolved from a directory entry, passes the shared Sprint 1 through 6.5 validation: safe relative POSIX paths, the transient-path policy, rejection of `.git` as any path component, and the all-platform case-insensitive final-destination collision rules.

Duplicate and overlapping selections are errors, reported with their line numbers: an entry repeated verbatim, two entries resolving the same source or colliding destinations, a file entry also covered by a directory entry, and a directory entry that equals, contains, or is contained by another directory entry.

All release-list diagnostics identify the release-list path, the line number, and the offending entry.

## Directory expansion

Directory expansion is deterministic: each listed directory is walked with directory members ordered by Unicode code point at every level, and every resolved file is validated and recorded in the inventory as if it had been listed individually.

Expansion distinguishes hard errors from deliberate exclusion. These members are errors: any symbolic link, whether or not it escapes the content root; any member whose path contains a `.git` component; and any member whose resolution escapes the content root. These members are silently excluded: files and components matching the existing transient policy (Jupyter checkpoints, `__pycache__`, `.DS_Store`, editor droppings), and any member whose name begins with a dot. The plan reports, per directory entry, the count of excluded members, so a surprising exclusion is visible at review time. A dotfile can still be published by listing it explicitly.

Within a configured Jupytext root, expansion additionally excludes every `.md` and `.ipynb` member. Authoring Markdown and notebooks in a Jupytext root are published only by individual listing under the notebook contract below; a directory entry there covers supporting material such as data files and images without sweeping in authoring sources or generated artifacts.

A directory entry that resolves to zero files after exclusion is an error: an allowlist entry that publishes nothing is a mistake.

Directory expansion resolves the working tree, and a working tree can contain files that a fresh CI checkout will not. To keep `ccc plan` locally identical to the plan CI publishes, expansion requires each resolved member to be tracked by Git when the content root lies inside a Git work tree: an untracked member is an error naming the file and the directory entry that resolved it. When the content root is not inside a Git work tree, the check is skipped and the plan records that it was skipped. Tracked status is used only to reject an ambiguous expansion; it never adds a file to the export.

## Notebook contract

Outside every configured Jupytext root, a listed `.ipynb` is an ordinary source file with byte-for-byte staging, preserving current version-1 behaviour for courses that publish notebooks as plain files.

Within a configured Jupytext root, every listed `.ipynb` is staged normalized: outputs and execution counts stripped, notebook JSON validated, canonical nbformat serialization, using the Sprint 3 normalization with Sprint 6.5's semantic comparison rules. A notebook inside a Jupytext root can never publish raw outputs. The staged bytes are produced as follows.

- When a same-stem supported Markdown source exists, the staged notebook is generated in the temporary staging tree from that Markdown source. If a private same-stem `.ipynb` also exists, it must additionally pass the semantic pair-synchronization comparison against the Markdown, and drift is an error. This preserves the INSY7130 guarantee — what the instructor validated is what publishes — with no `[[notebook]]` tables.
- When no Markdown source exists but the private notebook does, the staged notebook is its normalized form.
- When neither exists, the entry is an error.

A supported Jupytext source in Sprint 7 is a same-stem `.md` file readable by Jupytext; other Jupytext formats are future work. A staged notebook under a Jupytext root is never executable: its Sprint 6.5 `executable` value is false regardless of any source file's mode, since a generated notebook has no private notebook whose mode could be consulted. The private notebook need not be tracked or present for the generated mode. This supports courses such as INSY7120, where MyST Markdown is authoritative and paired notebooks are ignored generated files. The builder must not apply this contract outside an explicitly configured Jupytext root.

For a generated notebook, `build` and `verify` also fail if the Markdown source is absent, cannot be converted by the course's Jupytext configuration, or produces an invalid notebook. Course Courier never mutates the source checkout; local authoring tools may synchronize and format private pairs before commit.

The inventory's `notebook_exports` array records each Jupytext-root notebook with its `destination`, staged `size_bytes` and `sha256`, a `generated` Boolean, its `markdown` source when one was used, and its `source` private notebook when one exists. Version-1 manifests keep their existing `notebook_exports` shape unchanged.

## Publication safety

The release list is the complete desired export inside `public.managed_subtree`. The existing publish Action may remove a public managed file that is no longer resolved from the list. This is intentional and must be visible in `ccc plan`, `ccc verify`, and the Action's review artifact before publication.

The existing destination, branch, managed-subtree, staging, verification, comparison, environment-token, and protected-branch rules remain unchanged. The verified inventory for a version-2 manifest includes `release_manifest_sha256`, the SHA-256 of the raw release-list bytes, alongside `manifest_sha256`; the publication commit message includes both digests. A malformed, duplicate, unsafe, nonexistent, or destination-colliding entry fails before the public checkout is modified.

The publish Action's optional reviewed-hash gate must cover the file that actually selects content. The Action gains an optional `expected_release_manifest_sha256` input. For a version-2 manifest, the two digests are supplied together or not at all - either one without the other is an error - and each supplied digest must match the newly built inventory; a reviewed manual publish therefore gates both policy and selection. An automatic protected-branch workflow may continue to omit both.

No release list is inherited automatically. In particular, a legacy `RELEASES.txt` may be stale, may name generated files, or may have been designed for a former `pending/` layout. Adoption is an explicit migration that resolves and reviews the current intended export.

## Course applicability

| Course | Sprint 7 use | Required handling |
| --- | --- | --- |
| INSY3010 | Direct adoption | Use a new active list for its Fall 2026 `content/` tree; do not import the stale legacy list. |
| INSY7130 | Direct adoption | Replace repeated identity exports with a list and configure its lecture directories as Jupytext roots; the unified notebook contract preserves pair synchronization with no `[[notebook]]` tables. |
| INSY7120 | Generated-notebook adoption | Configure its Jupytext roots and list each student `.ipynb` target individually; directory entries there cover supporting material only, since expansion excludes `.md` and `.ipynb` under a root. |
| INSY6500 | Deferred | Its retired release list defines no current release set; migrate only after the post-Fall content structure is chosen. |
| INSY7970 | Per-target only | Do not apply one root list to the whole course workspace. Canvas material, grading content, and nested project repositories require separately bounded publication configurations, if any. |

## Non-goals

- Sprint 7 does not infer public files from their location, file extension, Git ignore rules, or an adjacent same-named Markdown file outside configured Jupytext roots. Git tracked status is consulted only to reject an ambiguous directory expansion, never to include a file.
- It does not publish Canvas exports, grading content, secrets, or nested Git repositories.
- It does not replace local Jupytext or Ruff authoring hooks.
- It does not migrate any course or alter an existing public repository merely by adding support for version 2.

## Implementation and verification

1. Add version-2 configuration parsing and `RELEASES.txt` parsing with line-numbered diagnostics, duplicate and overlap detection, source/destination validation, and deterministic directory expansion, reusing the shared Sprint 1 through 6.5 path validation.
2. Preserve the version-1 parser and prove unchanged build, verification, and Action behaviour for existing manifests.
3. Add the unified Jupytext-root notebook contract, including fixture tests where the private `.ipynb` is absent, present and synchronized, present and drifted, and where conversion or source validation fails.
4. Extend plans, inventories, review artifacts, Action inputs, trigger guidance, and commit provenance to identify the release list, its digest, exclusion counts, and generated outputs.
5. Test direct migrations using representative INSY3010 and INSY7130 manifests, then test INSY7120's MyST-plus-generated-notebook layout without modifying those course repositories.
6. Publish a new Course Courier release only after the acceptance cases below are covered by automated tests.

## Acceptance tests

The test suite must cover the following in addition to existing behaviour.

- Version-2 manifests reject `[[export]]` and `[[notebook]]` tables; version-1 manifests reject `release_manifest` and `[notebooks]`; `release_manifest` outside the content root, missing, or a symbolic link is rejected; `jupytext_roots` entries that are `.`, missing, nested, or overlapping are rejected.
- Release-list parsing rejects a BOM, accepts CRLF and stripped whitespace, ignores blank and comment lines, rejects `#` inside an entry, and rejects every arrow malformation: repeated `->`, empty side, unspaced arrow, and mixed file/directory shapes.
- Verbatim duplicates, colliding sources or destinations, a file covered by a directory entry, and equal, nested, or overlapping directory entries fail with the release-list path, line number, and entry in the diagnostic.
- Directory expansion is deterministic; a symbolic-link member, a `.git` component, and an escaping member are errors; transient files and dotfiles are excluded with per-entry counts reported in the plan; an entry resolving to zero files is an error; `.md` and `.ipynb` members are excluded under a Jupytext root; expanded members participate in case-insensitive final-destination collision checks.
- With the content root in a Git work tree, an untracked expanded member is an error naming the file and entry; outside a work tree the check is skipped and the plan records the skip.
- Under a Jupytext root: a listed notebook with only a Markdown source is generated and normalized; with a synchronized private notebook it builds and drift fails; with only a private notebook it is normalized; with neither it fails; malformed Markdown, failed conversion, and invalid notebook JSON fail; staged notebooks under a root never contain outputs or execution counts; a listed notebook outside every root is byte-copied.
- The version-2 inventory contains `release_manifest_sha256`; the publication commit message contains both digests; the publish Action rejects `expected_manifest_sha256` without `expected_release_manifest_sha256` for a version-2 manifest and rejects a mismatch of either digest before the public checkout is modified.
- Representative version-1 manifests produce byte-identical plans, inventories, and staged trees before and after Sprint 7.

Fixtures exercising the tracked-member rule must run inside a real Git work tree; a bare temporary-directory fixture exercises only the documented skip path. Sprint 6.5's script-test harness in `tests/test_review.py` already provides the repository-construction helpers these fixtures need.

## Definition of done

Sprint 7 is complete when a version-2 course can publish an explicit `RELEASES.txt` allowlist with minimal policy TOML, version-1 courses behave identically, recursive directories and rename mappings are safe, deterministic, and identical between a local plan and CI, the unified Jupytext-root contract generates stripped staged notebooks without a tracked private notebook while preserving pair synchronization where one exists, the reviewed-hash gate covers both the policy manifest and the release list, and the review and publish artifacts make the complete resolved export, every exclusion, and any removals inspectable.
