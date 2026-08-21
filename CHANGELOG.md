# Changelog

## Unreleased

- Add `executable` to plan, build, verify, and review file records. It is an additive field that represents Git-compatible executable state.
- Compare only Git-representable entries in review JSON: regular files and symbolic links, with `.git` entries excluded at any depth on both sides. Bare directory entries are no longer reported, because Git cannot represent an empty directory and a directory-only difference can never produce a publishable change.
- Remove the previously undocumented `notebooks` key from plan and inventory JSON. Declared notebook pairs remain validated internally, and normalized staged notebook exports remain available through `notebook_exports`.
- Harden manifest validation, staged-tree verification, and reusable GitHub Action execution before Sprint 7.
