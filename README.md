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

## Interface

The implementation is a small Python CLI, with optional thin `just` aliases:

```text
course-courier plan   --config content/PUBLISH.toml
course-courier build  --config content/PUBLISH.toml --output /tmp/course-public
course-courier verify --config content/PUBLISH.toml --output /tmp/course-public
```

`plan` reports the resolved export without writing it. `build` produces a clean export. `verify` checks the staged result and emits its inventory.

The tool does not itself need GitHub credentials. The repository Action owns the final clone, diff, commit, and push.

## Manifest

A version-2 course keeps a compact `content/PUBLISH.toml` for publication policy and selects content with a plain-text `RELEASES.txt` allowlist.

```toml
version = 2
release_manifest = "RELEASES.txt"

[public]
repository = "olearydj/INSY3010"
branch = "main"
managed_subtree = "course"

[notebooks]
jupytext_roots = ["lectures"]
```

`RELEASES.txt` is UTF-8 plain text: blank lines and `#` comment lines are ignored, every other line is an allowlisted entry relative to the content root, a trailing slash publishes a directory recursively, and `source -> destination` handles the uncommon rename.

```text
# Course-wide material
LICENSE
README.md

# Student-facing lectures
lectures/01a-course-introduction/01a-course-introduction.pptx
lectures/01b-operators-and-expressions/01b-operators-and-expressions.ipynb
```

Directory entries are validated and filtered during expansion: symlinks, `.git` components, and (inside a Git work tree) untracked members are errors, while transient files and dotfiles are excluded with counts reported in the plan. `docs/sprint-7.md` documents the complete format, including the duplicate, overlap, and rename rules.

Version-1 manifests, which enumerate each file as a `[[export]]` table and declare notebook pairs as `[[notebook]]` tables, remain fully supported with unchanged behaviour; `docs/sprint-1.md` and `docs/sprint-3.md` document that format. New courses should adopt version 2.

## Notebook policy

When a course uses Jupytext, its Markdown is the authoring source and the paired notebook is the student artifact. A listed notebook beneath a configured `jupytext_roots` directory is always staged normalized - outputs and execution counts stripped, notebook JSON validated - and is generated from its same-stem Markdown source when one exists. A private paired notebook need not be tracked or present; when it is, it must be synchronized with the Markdown before it can publish. A listed notebook outside every Jupytext root is copied byte for byte.

The release list normally names the notebook, not private authoring notes or source Markdown. A course may explicitly list source Markdown when that is an instructional choice.

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
