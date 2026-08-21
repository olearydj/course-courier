# Course Courier

`course-courier` is a deliberately small course-content publisher: it carries an explicit selection of student-facing material from a private teaching repository to its public GitHub repository.

Sprints 1 through 6.5 implement the planner, safe local staging, verification, optional staged-only notebook normalization, review and publish Actions, a protected-branch automatic synchronization workflow, and hardening of manifest, file-mode, and Action-script boundaries. Sprint 7 adds version-2 manifests, where a plain-text `RELEASES.txt` allowlist selects content and configured Jupytext roots stage normalized student notebooks generated from Markdown sources. Enabling a course workflow remains a maintainer decision.

## Problem

Several course repositories previously used `classpub`'s `pending/` → `preview/` → public-repository workflow. Current material now lives under `content/` in unit directories, alongside private planning material and authoring sources. Copying `content/` wholesale is unsafe, while the former workflow is more machinery than the task requires.

The intended author experience is:

1. Add or remove an explicit release entry.
2. Commit and push the active semester branch.
3. GitHub publishes exactly that selection to the existing public repository.

## Scope and principles

- **Allowlist only.** A file is public only when named in the manifest.
- **One source of truth.** The private course repository owns the manifest and source material; the public repository is generated and is never edited by hand.
- **Safe by default.** Reject entries outside `content/`, path traversal, symlinks that escape the source tree, Jupyter checkpoints, and other transient files.
- **No local preview state.** Builds use a temporary staging directory; there is no tracked or persistent `preview/` tree.
- **Same command locally and in CI.** CI calls the same builder used for a `plan` or `build` review.
- **Course-neutral.** INSY3010, INSY7130, and comparable repositories should need only per-course configuration and an allowlist.

## Proposed interface

The implementation is a small Python CLI, with optional thin `just` aliases:

```text
course-courier plan   --config content/PUBLISH.toml
course-courier build  --config content/PUBLISH.toml --output /tmp/course-public
course-courier verify --config content/PUBLISH.toml --output /tmp/course-public
```

`plan` reports the resolved export without writing it. `build` produces a clean export. `verify` checks the staged result and emits its inventory.

The tool does not itself need GitHub credentials. The repository Action owns the final clone, diff, commit, and push.

## Proposed manifest

The manifest is intentionally boring and explicit. It supports a file or a directory export and a public destination; it does not infer that all adjacent files in a source directory should be public.

```toml
version = 1

[public]
repository = "olearydj/INSY3010"
branch = "main"
managed_subtree = "course"

[[export]]
source = "README.md"
destination = "README.md"

[[export]]
source = "LICENSE"
destination = "LICENSE"

[[export]]
source = "lectures/01a-course-introduction/01a-course-introduction.pptx"
destination = "lectures/01a-course-introduction/01a-course-introduction.pptx"

[[export]]
source = "lectures/01b-operators-and-expressions/01b-operators-and-expressions.ipynb"
destination = "lectures/01b-operators-and-expressions/01b-operators-and-expressions.ipynb"
```

Sources are relative to the configured `content/` root. Directories may be allowed later, but must be opt-in and copied recursively only after filtering and validation. Initial releases should prefer individual files.

## Notebook policy

When a course uses Jupytext, its Markdown is the authoring source and the paired notebook is the student artifact. Before export, the builder should:

1. Synchronize declared Markdown/notebook pairs.
2. Fail if synchronization changes a tracked notebook unexpectedly in CI.
3. Strip notebook outputs and execution counts in the staged copy only.
4. Validate notebook JSON after stripping.

The manifest normally exports the notebook, not private authoring notes or source Markdown. A course may explicitly publish source Markdown when that is an instructional choice.

## GitHub Action

The Action is intentionally linear:

1. Trigger on the active semester branch when `content/**`, `PUBLISH.toml`, or the shared publisher version changes; allow manual dispatch.
2. Run `course-courier build` into a runner temporary directory.
3. Run `course-courier verify` and retain the inventory as an artifact.
4. Clone the existing public repository into another temporary directory.
5. Mirror the staged export with deletion enabled only inside that clone.
6. Commit only when a diff exists, identifying the private commit SHA and manifest hash.
7. Push `main` with a fine-grained token or GitHub App credential limited to the target public repository.

For a first migration, the Action should be manually dispatched and produce a reviewable artifact or pull request before it performs the public push.

## Relationship to `content/repos`

INSY7970's `content/repos` pattern is suitable for standalone public example repositories: source directory → temporary Git repository → one public repo. Course Courier uses the same temporary-staging idea, but publishes one rolling course repository from a fine-grained allowlist. The two can later share small path-validation or Git-mirroring helpers without becoming one framework.

## Non-goals

- No replacement for Git or GitHub Actions.
- No persistent preview directory, release-state database, or status taxonomy.
- No automatic publication based merely on a folder's location or filename.
- No attempt to manage Canvas, assignments, or per-lab public repositories.

## Adoption plan

1. Complete and test the planner with fixture course trees.
2. Add staged `build` and `verify` commands.
3. Add an INSY3010 manifest and run its first release in review mode.
4. Enable the Action after the staged export matches the intended public tree.
5. Reuse the same tool and manifest style in INSY7130, then evaluate shared helpers for standalone `content/repos` projects separately.
