# Course Courier — Sprint 6.5 specification

## Purpose

Sprint 6.5 hardens the completed Sprints 1 through 6 publication path before Sprint 7 adds recursive release entries, rename mappings, and generated notebooks. It corrects safety and consistency gaps without changing the normal course-maintainer workflow: edit selected private content, commit, and push the active protected branch.

The sprint applies to version-1 manifests as well as any later manifest version. It does not add `RELEASES.txt` support or migrate a course.

## Manifest and Action boundary

The planner must validate `public.branch` as a Git branch name using an implementation equivalent to Git's branch-ref rules. It must reject empty names, the single name `@`, the reserved name `HEAD`, names beginning with `-`, control characters, whitespace, `..`, `@{`, forbidden ref characters, leading or trailing slashes, repeated slashes, leading dots, components ending in `.`, and components ending in `.lock`. The error identifies `public.branch` and occurs during planning, before staging or an Action checkout.

Every destination path and `public.managed_subtree` must reject `.git` as any path component. This prevents a manifest from staging Git administrative paths, asking review to compare them, or relying on the publisher's rsync exclusion to silently omit them. The publisher and reviewer have one rule: no managed export contains a `.git` component.

Composite Actions must treat values resolved from an inventory as untrusted data until they are placed in shell variables. A `run:` block may not contain GitHub-expression syntax (`${{`) at all. Each required value is passed through the step's `env:` mapping, or through the default environment variables the runner already provides, and is referenced only as a quoted shell expansion. This includes paths, repository and branch information, manifest digests, and commit-message values. Action metadata may still pass validated values to a JavaScript Action input such as `actions/checkout`.

The actions use the Course Courier uv environment for every Python invocation, including JSON parsing helpers. Their internally used third-party Actions are pinned to immutable commit SHAs, matching the caller-facing pinning guidance.

## Build atomicity

`ccc build` constructs and fully verifies its temporary staging directory before it attempts to publish that directory at the requested output path. A verification error therefore leaves no builder-created output path behind.

The output path is checked before work begins and immediately before the final move. Those checks provide best-effort detection of a concurrent creation and Course Courier never intentionally overwrites or removes a path it did not create; POSIX rename cannot make that guarantee atomic for an already existing empty directory. Temporary build material is removed on all failures. The builder never mutates the private content tree.

## Review and publish consistency

The plan and verified inventory record an `executable` Boolean for every exported regular file. The Boolean is true when any execute permission bit is set on the source, matching Git's single-bit file-mode model and the modes a public checkout materializes. Staging sets the staged file's mode from that Boolean rather than copying raw permission bits, and `ccc verify` enforces it alongside byte size and SHA-256. A staged executable-bit change is therefore a verification failure rather than an unrecorded change that publication can propagate.

Tree comparison includes a regular file's executable-bit state in addition to kind, byte size, and SHA-256 digest. A source mode change that is preserved by staging is therefore reported as changed and is synchronized by publication. Every regular-file object in review JSON, including added, removed, and each side of a changed entry, carries `executable`; directory and symlink objects retain their existing kind-only representation.

The publisher completes its read-only comparison before it creates a missing non-root public managed directory. A matching managed tree is a true no-op after checkout: it does not create directories, stage files, commit, or push. When a difference requires synchronization, directory creation and bounded rsync mirroring occur afterward. After mirroring, the publisher checks `git status --porcelain`; an empty result when review reported a change fails with a clear consistency diagnostic instead of attempting a bare `git commit`.

The reviewer's Git exclusion is aligned with the publisher: `.git` is not a valid managed export component, and no recursive comparison or rsync operation admits a nested `.git` directory as content. A nested `.git` directory found in the public tree is therefore invisible to comparison and is never deleted by mirroring; the aligned exclusions prevent the alternative in which review reports a removal that rsync refuses to perform, which would trip the consistency diagnostic on every run. Removing such a directory from a public repository is a manual operation.

## Notebook comparison normalization

Declared notebook-pair synchronization compares normalized notebook structures rather than incidental Jupytext serialization details. It ignores `jupytext.text_representation`, removes an otherwise empty `jupytext` metadata mapping, and ignores `nbformat_minor`. It continues to compare meaningful cell structure, cell source, and non-representation metadata after outputs and execution counts are normalized away.

This prevents a false out-of-sync failure when Markdown parsing and a private notebook differ only in Jupytext representation metadata or minor notebook format version. It does not relax source validation or allow the builder to modify a private notebook.

## Diagnostics, inventory, and compatibility

Planner diagnostics identify the field actually being validated. In particular, a transient `[[notebook]].markdown` path is reported as the Markdown field, not as a generic source field. Duplicate-destination diagnostics report the resolved final destination, including the managed subtree, so the collision is actionable.

Destination collisions remain case-insensitive on every platform. This deliberately stricter policy avoids a manifest that is valid on one maintainer's filesystem but cannot be represented safely on another's. Sprint 1 documentation is updated to state this platform-independent rule. Sprint 2's inventory schema and its build-contract wording about preserving raw mode bits, together with Sprint 4's review JSON contract, are likewise updated for the `executable` field, and the release notes mention the additive `executable` field alongside the `notebooks` key removal, since the same consumers are affected by both schema changes.

The plan and inventory schema has one documented representation for notebook-pair declarations. Sprint 6.5 removes the redundant undocumented `notebooks` key from plan and inventory JSON; `notebook_exports` remains the documented staged-output record where applicable. Consequently, `ccc plan` intentionally does not expose declared notebook pairs, while `build` and `verify` retain their observable normalized exports. This schema cleanup is backward-incompatible only for consumers of an undocumented field and is called out in the release notes.

Comparison of non-representation notebook metadata remains strict. A metadata difference such as a private `kernelspec` absent from Markdown is treated as an out-of-sync pair, which is the current deliberate policy. A future change requires evidence from a course and its own specification; Sprint 6.5 does not broaden normalization beyond known representation-only fields.

## Action structure and testability

Composite Action YAML remains declarative glue. The prepare, compare, and publish shell logic moves into versioned scripts under the Action directories, with their dynamic values supplied through documented environment variables. The scripts have no GitHub-expression syntax and can be invoked by automated tests against temporary staged trees and temporary Git checkouts.

Tests exercise a matching non-root tree, a missing public boundary, a changed tree, and the review-changed-but-Git-clean consistency failure through those scripts. YAML structural tests remain useful for pinning, input wiring, and the absence of `${{` inside `run:` blocks, but ordering and no-op semantics are proven by script behaviour rather than string matching.

## Acceptance tests

The test suite must cover the following in addition to existing behaviour.

- Reject malformed, non-string, missing, and unsupported-version manifest values, including malformed `managed_subtree` and each enumerated invalid branch-name rule.
- Reject `.git` in a destination or managed subtree, including nested components.
- Verify that planner failure, copy failure, source changes during build, and staged-tree verification failure leave no builder-created output and leave all source files unchanged.
- Verify that executable state is recorded in plan and inventory entries, derived as true for any set execute bit (including an owner-only 0o700 source), preserved by build, enforced by verify, and reported consistently for every regular file in review JSON.
- Exercise the Action scripts with a matching non-root tree that does not create its public boundary, a changed tree, and a review-changed-but-Git-clean failure.
- Verify that a nested `.git` directory in the public tree is ignored by comparison, never deleted by mirroring, and does not cause a consistency failure on an otherwise matching or changed tree.
- Structurally verify that composite Action shell blocks use environment variables for dynamic values, use uv-managed Python, pin their internal third-party Actions by SHA, and contain no `${{` inside `run:` blocks.
- Verify declared notebook pairs with malformed Markdown, malformed notebook JSON, duplicate declarations, an empty Jupytext metadata mapping after normalization, and differing `nbformat_minor` values.
- Verify that a changed source file changes the planned inventory digest.
- Verify field-specific transient-path and final-destination collision diagnostics, the documented all-platform case-insensitive collision rule, and the absence of the undocumented `notebooks` JSON key.

Tests must retain the existing valid manifest, staged-only notebook normalization, review, and publish cases. A version-1 manifest that was valid before this sprint remains valid unless it relies on an unsafe `.git` path or invalid Git branch name.

## Non-goals

- No new manifest syntax, directory expansion, rename mapping, or generated-notebook support.
- No change to public repository selection, protected-branch workflow ownership, GitHub Environment configuration, or token scope.
- No source-tree formatting, Jupytext synchronization, or notebook rewriting by Course Courier.

## Definition of done

Sprint 6.5 is complete when manifest-derived values cannot alter Action shell syntax, unsafe Git administrative paths are rejected during planning, failed builds leave no builder-created output, executable state is planned, verified, reviewed, and published consistently, no-difference publication does not modify its checkout, semantic notebook comparison avoids representation-only false failures, internal Action dependencies are immutably pinned, and the listed regression tests pass alongside all earlier sprint tests.
