# Changelog

## Unreleased

- Add version-2 manifests: `PUBLISH.toml` keeps publication policy while `RELEASES.txt` selects content with identity entries, `source -> destination` renames, and recursive directory entries with line-numbered diagnostics, duplicate and overlap rejection, deterministic expansion, transient and dotfile exclusion with reported counts, and Git-tracked-member enforcement inside a work tree.
- Add the unified Jupytext-root notebook contract: a listed notebook beneath a configured root is always staged normalized, generated from a same-stem Markdown source when one exists (with pair synchronization enforced when a private notebook also exists), and is never executable.
- Record `release_manifest_sha256` in version-2 plans and inventories, include it in publication commit messages, and extend the publish Action's reviewed-hash gate with `expected_release_manifest_sha256`, required together with `expected_manifest_sha256` for version-2 manifests.

- Add `executable` to plan, build, verify, and review file records. It is an additive field that represents Git-compatible executable state.
- Compare only Git-representable entries in review JSON: regular files and symbolic links, with `.git` entries excluded at any depth on both sides. Bare directory entries are no longer reported, because Git cannot represent an empty directory and a directory-only difference can never produce a publishable change.
- Remove the previously undocumented `notebooks` key from plan and inventory JSON. Declared notebook pairs remain validated internally, and normalized staged notebook exports remain available through `notebook_exports`.
- Harden manifest validation, staged-tree verification, and reusable GitHub Action execution before Sprint 7.
