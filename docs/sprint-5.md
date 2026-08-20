# Course Courier — Sprint 5 specification

## Purpose

Sprint 5 adds an explicitly gated publish Action. It is the first component allowed to modify a public repository, but it does so only after rebuilding and verifying the private export, confirming an operator-supplied manifest hash, and receiving the literal confirmation value `publish`.

## Publish Action

The `publish/action.yml` composite Action accepts `config`, `public_token`, `expected_manifest_sha256`, and `confirmation`. The token is required and must have contents read/write access only to the manifest-selected public repository. The Action rejects any confirmation other than `publish` and rejects an expected hash that differs from the newly built and verified inventory.

The Action uses the same locked Course Courier project, `build`, `verify`, and comparison module as Sprint 4. It checks out the public repository's manifest-selected branch, captures a pre-publish review artifact, and exits without writing when the managed trees match.

When differences exist, the Action mirrors the staged managed boundary into the checkout. Deletion is enabled only inside that boundary. A root-managed manifest (`managed_subtree = "."`) intentionally makes the entire public working tree, except `.git`, deletable; a maintainer must therefore review the Sprint 4 artifact and use the explicit confirmation gate before publishing it.

The Action configures a fixed bot identity, commits only if the public checkout has a diff, and pushes `HEAD` to the manifest-selected branch. The commit message includes the private GitHub commit SHA and manifest SHA. It uploads the inventory and pre-publish review JSON regardless of whether a commit was necessary.

## Calling workflow

A course repository uses a separate manually dispatched workflow. It must run in a protected GitHub Environment such as `public-course-publish`, require reviewers in repository settings, pass a fine-grained write token through a secret, and require the operator to paste the reviewed manifest SHA.

```yaml
name: Publish reviewed course export

on:
  workflow_dispatch:
    inputs:
      manifest_sha256:
        description: SHA-256 from the reviewed Course Courier inventory
        required: true
        type: string
      confirmation:
        description: Type publish to allow the public-repository write
        required: true
        type: string

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
          expected_manifest_sha256: ${{ inputs.manifest_sha256 }}
          confirmation: ${{ inputs.confirmation }}
```

## Safety constraints

- The Action has no default token fallback for publishing.
- The public target comes only from the verified manifest, never workflow input.
- The Action fails before checkout mutation when confirmation or manifest-hash gates fail.
- It cannot modify files outside a non-root managed subtree.
- It does not force-push, create branches, alter repository settings, or publish Canvas content.
- A no-diff run creates no commit and reports `published=false`.

## Definition of done

Sprint 5 is complete when publish Action metadata is structurally tested, the shell implementation contains all gates and bounded mirror behaviour, its non-GitHub components remain covered by the existing build, verify, and review suite, and no course workflow is enabled without an explicit maintainer decision.
