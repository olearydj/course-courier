# Course Courier — Sprint 4 specification

## Purpose

Sprint 4 provides a review-only reusable GitHub Action. It builds and verifies the private course export, checks out the manifest-selected public repository, compares only the managed boundary, and uploads an inventory plus structured diff artifact. It never commits, pushes, opens pull requests, or changes the public repository.

## Composite Action

The repository-root `action.yml` exposes `course-courier-review`. Its required `config` input is a manifest path relative to the calling course repository. Its optional `public_token` input is used only to read the target repository; callers should provide a fine-grained read-only token only when the target is private. Public repositories need no additional credential.

The Action uses uv to run the pinned Course Courier project at `github.action_path`. It runs `ccc build`, `ccc verify`, reads `public.repository`, `public.branch`, and `public.managed_subtree` from the verified inventory, and checks out that public repository with credentials disabled after checkout.

The Action outputs `changed`, `inventory_path`, and `review_path`. It uploads both JSON files as a `course-courier-review` artifact. A changed comparison is a successful review result, not an Action failure; invalid manifests, build failures, verification failures, checkout failures, or comparison errors fail the Action.

## Comparison contract

The comparison is read-only and deterministic. It compares the Git-representable entries of the staged managed boundary and the corresponding public boundary: regular files and symbolic links. `.git` entries are excluded at any depth on both sides, matching the publisher's rsync exclusion; a nested public `.git` directory is neither compared nor removed by publication and requires manual cleanup. Bare directories are not compared, because Git cannot represent an empty directory: a directory-only difference could never produce a publishable change, and reporting one would wedge the publisher's consistency check. For `managed_subtree = "."`, the complete public working tree apart from `.git` entries is compared. For a non-root subtree, files outside that subtree are not inspected.

The review JSON has a Boolean `changed` value and destination-sorted `added`, `removed`, and `changed_entries` arrays. Each item identifies its relative path and its kind, file or symlink; regular files also report SHA-256, size, and an `executable` Boolean. A missing public managed subtree is treated as an empty public tree, producing additions rather than an error.

## Calling workflow

The calling course repository owns triggers. Its review workflow belongs in `.github/workflows/`, uses least-privilege `contents: read`, triggers on the active semester branch for `content/**` and the manifest, and permits manual dispatch. It must pin the released Course Courier action to an immutable commit SHA before production use.

```yaml
name: Review public course export

on:
  push:
    branches: [fall-2026]
    paths: [content/**]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<immutable-SHA>
      - uses: olearydj/course-courier@<immutable-SHA>
        with:
          config: content/PUBLISH.toml
```

## Exclusions

Sprint 4 does not push, commit, open a pull request, or configure a workflow in a course repository. Those are explicit Sprint 5 decisions after an inspected review artifact.

## Definition of done

Sprint 4 is complete when the comparison module is tested, the composite Action has no write-capable publication step, the Action metadata and workflow example are validated structurally, and a course maintainer can use its artifacts to inspect an INSY7130 release candidate.
