# Changelog

## 0.3.1 - 2026-08-20

- Reject `..` components in the `init-workflow` config path: lexical normalization could otherwise erase a redirecting symlink from the escape check.

## 0.3.0 - 2026-08-20

- Add `ccc init-workflow`, which scaffolds a course repository's publish workflow at the Git work-tree root with YAML-safe rendering, derived trigger paths and concurrency group, validated branch input, and immutable action pins resolved from the running release's annotated tag (`--sha` overrides for offline or unreleased builds). The command refuses to overwrite without `--force`, replaces atomically, and prints the remaining manual setup checklist.

## 0.2.0 - 2026-08-20

- Add version-2 manifests: `PUBLISH.toml` keeps publication policy while `RELEASES.txt` selects content with identity entries, `source -> destination` renames, and recursive directory entries with line-numbered diagnostics, duplicate and overlap rejection, deterministic expansion, transient and dotfile exclusion with reported counts, and enforcement inside a Git work tree that every selected source is tracked, keeping a local plan identical to what CI publishes.
- Add the unified Jupytext-root notebook contract: a listed notebook beneath a configured root is always staged normalized, generated from a same-stem Markdown source when one exists (with pair synchronization enforced when a private notebook also exists), and is never executable.
- Record `release_manifest_sha256` in version-2 plans and inventories, include it in publication commit messages, and extend the publish Action's reviewed-hash gate with `expected_release_manifest_sha256`, required together with `expected_manifest_sha256` for version-2 manifests.

- Add `executable` to plan, build, verify, and review file records. It is an additive field that represents Git-compatible executable state.
- Compare only Git-representable entries in review JSON: regular files and symbolic links, with `.git` entries excluded at any depth on both sides. Bare directory entries are no longer reported, because Git cannot represent an empty directory and a directory-only difference can never produce a publishable change.
- Remove the previously undocumented `notebooks` key from plan and inventory JSON. Declared notebook pairs remain validated internally, and normalized staged notebook exports remain available through `notebook_exports`.
- Harden manifest validation, staged-tree verification, and reusable GitHub Action execution before Sprint 7.
