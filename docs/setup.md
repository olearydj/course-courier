# Course Courier — Course setup guide

This guide takes a private course repository from nothing to automatic publication: a push to the protected course branch rebuilds, verifies, and synchronizes an explicit allowlist of student-facing material into a public GitHub repository. It reflects Course Courier v0.3.0 and the version-2 manifest format.

## Prerequisites

- A private course repository whose publishable material lives under a single content root, conventionally `content/`. Everything Course Courier publishes must be tracked by Git inside that root.
- Authority to create the public repository, a fine-grained personal access token, and a GitHub Environment on the private repository.
- [uv](https://docs.astral.sh/uv/) installed locally for dry runs. Nothing else is installed into the course project; the CLI runs from the published release.

## 1. Create the public repository

Create an empty public repository (for example `olearydj/INSY3010`) with default branch `main`. Do not seed it with a README or license; Course Courier generates its entire managed tree.

Decide the managed boundary now. `managed_subtree = "."` gives Course Courier ownership of the whole repository: publication may delete any file not resolved from the release list, so the repository must contain nothing independently maintained (no hand-edited `CNAME`, no `.github/` workflows). If the public repository needs such files, choose a subtree such as `managed_subtree = "course"` and Course Courier will never touch anything outside it.

## 2. Add the manifest and release list

Create `content/PUBLISH.toml` holding publication policy only:

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

The `[notebooks]` table is optional. Configure `jupytext_roots` when lecture notebooks are authored as Jupytext Markdown: a listed `.ipynb` beneath a root is always staged with outputs and execution counts stripped, and is generated from its same-stem `.md` source when one exists. A private paired notebook may remain untracked or gitignored; when present it must be synchronized with the Markdown. Add generated notebooks to `.gitignore` if the Markdown is authoritative.

Create `content/RELEASES.txt`, the complete allowlist of what publishes:

```text
# Course-wide material
LICENSE
README.md

# Student-facing lectures
lectures/01a-course-introduction/01a-course-introduction.pptx
lectures/01b-operators-and-expressions/01b-operators-and-expressions.ipynb

# Supporting material, published recursively
data/
```

Format rules, in brief: paths are relative to the content root; blank lines and `#` comment lines are ignored (inline comments are not supported); a trailing slash publishes a directory recursively; `source -> destination` handles the uncommon rename, file to file or directory to directory. Directory expansion excludes dotfiles and transient files (with counts reported in the plan) and, beneath a Jupytext root, excludes `.md` and `.ipynb` members so notebooks are always listed individually. Duplicate, overlapping, unsafe, or `.git`-touching entries are line-numbered errors. `docs/sprint-7.md` documents the complete format.

The release list is the whole export: a file removed from the list is removed from the public repository on the next publication. That is the intended behaviour, not an accident to guard against.

## 3. Dry-run locally

Commit (or at least `git add`) the content you intend to publish first; inside a Git work tree, Course Courier refuses to publish untracked sources so that a local plan resolves exactly what CI will build from a clean checkout.

```bash
uvx --from git+https://github.com/olearydj/course-courier@v0.3.0 ccc plan --config content/PUBLISH.toml
uvx --from git+https://github.com/olearydj/course-courier@v0.3.0 ccc build --config content/PUBLISH.toml --output /tmp/course-public
uvx --from git+https://github.com/olearydj/course-courier@v0.3.0 ccc verify --config content/PUBLISH.toml --output /tmp/course-public
```

`plan` prints the resolved export as canonical JSON without writing anything; review its `exports`, `notebook_targets`, `directory_expansions`, and `source_tracking` fields until they match your intent. `build` stages the tree at a fresh output path (it never overwrites an existing one), and `verify` independently checks the staged result. Inspect the staged tree by hand before wiring up automation; it is byte-for-byte what will be published.

## 4. Create the publication token

Create a fine-grained personal access token scoped to the single public repository with Contents read and write permission and nothing else. Course Courier derives the push target only from the verified manifest, but the token itself should still be incapable of reaching anything but the public repository.

## 5. Configure the GitHub Environment

On the private repository, create an Environment named `public-course-publish`. Restrict its deployment branches to the publishing branch (for example `main` or the active semester branch), and add the token as the environment secret `COURSE_COURIER_PUBLIC_TOKEN`. The secret is then unavailable to any workflow run outside that environment and branch.

Protect the publishing branch itself so that automatic publication can only follow a deliberate merge or push to it.

## 6. Add the publish workflow

Scaffold `.github/workflows/course-courier-publish.yml` with the CLI, which derives the trigger paths, config path, and concurrency group from your manifest and pins both actions to verified immutable commit SHAs:

```bash
uvx --from git+https://github.com/olearydj/course-courier@v0.3.0 ccc init-workflow --config content/PUBLISH.toml --branch main
```

The command resolves its own release's commit SHA from the version tag on the official repository (pass `--sha` with a reviewed commit when offline), refuses to overwrite an existing workflow without `--force`, and finishes by printing the manual checklist covered in steps 4, 5, and 7. For reference, the generated workflow has this shape, with `<immutable-SHA>` values the command fills in:

```yaml
name: Publish course export

on:
  push:
    branches: [main]
    paths:
      - content/**
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: public-course-publish-<course>-main
  cancel-in-progress: false

jobs:
  publish:
    environment: public-course-publish
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<immutable-SHA> # v4.2.2
      - uses: olearydj/course-courier/publish@<immutable-SHA> # vX.Y.Z
        with:
          config: content/PUBLISH.toml
          public_token: ${{ secrets.COURSE_COURIER_PUBLIC_TOKEN }}
          confirmation: publish
```

Both actions are pinned to immutable commit SHAs; the comment records the human-readable version. Because `content/` contains `PUBLISH.toml` and `RELEASES.txt`, the trigger covers policy and selection changes as well as content changes. To upgrade a course later, re-run `init-workflow --force` from the newer Course Courier release.

## 7. First publication

Run the workflow once by hand from the Actions tab (`workflow_dispatch`) before relying on pushes. Every run uploads a `course-courier-publish-review` artifact holding the verified inventory and the pre-publish comparison; inspect it to confirm the additions, and confirm the public repository matches the staged tree you reviewed locally. A run that finds no difference is a successful no-op that creates no commit.

For a first migration you want gated on explicit review, dispatch with the optional reviewed-hash inputs: pass `expected_manifest_sha256` and `expected_release_manifest_sha256` together, copied from a reviewed inventory, and the Action refuses to publish if either file changed since the review. The routine protected-branch workflow omits both.

Publication commits in the public repository identify the private source commit and both digests, for example `Publish course content from <sha> (manifest <sha256>) (release list <sha256>)`, so every public state traces to an exact private commit and selection.

## Ongoing maintenance

The normal loop is: edit course material, update `RELEASES.txt` when the selection changes, commit, and push the publishing branch. Nothing publishes from other branches, from paths outside `content/`, or from files not named in the release list. To retire material, delete its line from `RELEASES.txt` and push; to upgrade Course Courier, update the pinned SHA in the workflow after reviewing the release notes.

## Common first-run failures

- `selected source is not tracked by Git`: the file is listed (or swept by a directory entry) but not committed; `git add` it or remove it from the selection.
- `entry overlaps the entry on line N`: a file is both listed and covered by a directory entry; keep one, except for notebooks under a Jupytext root, which are always listed individually.
- `declared Markdown pair is out of sync`: the private notebook drifted from its Markdown source; re-sync the pair locally (for example with `jupytext --sync`) and commit.
- `directory entry resolves to no publishable files`: everything in the directory was excluded as transient, hidden, or notebook material; list the survivors individually or remove the entry.
- `output path must not already exist`: `ccc build` never reuses an output directory; pass a fresh path.
