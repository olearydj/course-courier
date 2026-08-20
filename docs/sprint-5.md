# Course Courier — Sprint 5 specification

## Purpose

Sprint 5 adds a publish Action. It is the first component allowed to modify a public repository. It always rebuilds and verifies the private export, then compares it with the manifest-selected public branch before making a bounded update. A caller can optionally supply a reviewed manifest hash as an additional gate.

## Publish Action

The `publish/action.yml` composite Action accepts `config`, `public_token`, `expected_manifest_sha256`, and `confirmation`. The token is required and must have contents read/write access only to the manifest-selected public repository. The Action rejects an empty token or any confirmation other than `publish`. When supplied, `expected_manifest_sha256` must match the newly built and verified inventory; an automatic protected-branch workflow may omit it.

The Action uses the same locked Course Courier project, `build`, `verify`, and comparison module as Sprint 4. It checks out the public repository's manifest-selected branch, captures a pre-publish review artifact, and exits without writing when the managed trees match.

When differences exist, the Action mirrors the staged managed boundary into the checkout. Deletion is enabled only inside that boundary. A root-managed manifest (`managed_subtree = "."`) intentionally makes the entire public working tree, except `.git`, deletable; it therefore requires a carefully maintained manifest, a protected calling branch, and an environment-scoped token.

The Action configures a fixed bot identity, commits only if the public checkout has a diff, and pushes `HEAD` to the manifest-selected branch. The commit message includes the private GitHub commit SHA and manifest SHA. It uploads the inventory and pre-publish review JSON regardless of whether a commit was necessary.

## Calling workflow

A course repository can use a single `push` workflow for its protected `main` branch. It must run in a protected GitHub Environment such as `public-course-publish` and pass a fine-grained write token through an environment secret. A push under `content/`, including the manifest, rebuilds and synchronizes the public repository. The Action's artifact preserves the pre-publish inventory and comparison.

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

jobs:
  publish:
    environment: public-course-publish
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<immutable-SHA>
      - uses: olearydj/course-courier/publish@<immutable-SHA>
        with:
          config: content/PUBLISH.toml
          public_token: ${{ secrets.COURSE_COURIER_PUBLIC_TOKEN }}
          confirmation: publish
```

## Safety constraints

- The Action has no default token fallback for publishing and rejects an empty token.
- The public target comes only from the verified manifest, never workflow input.
- The Action fails before checkout mutation when its confirmation or optional manifest-hash gate fails.
- It cannot modify files outside a non-root managed subtree.
- It does not force-push, create branches, alter repository settings, or publish Canvas content.
- A no-diff run creates no commit and reports `published=false`.

## Definition of done

Sprint 5 is complete when publish Action metadata is structurally tested, the shell implementation contains its token, confirmation, optional reviewed-hash, and bounded mirror behaviour, its non-GitHub components remain covered by the existing build, verify, and review suite, and automatic course publication is limited to a maintainer-selected protected branch.
