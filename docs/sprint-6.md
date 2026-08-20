# Course Courier — Sprint 6 specification

## Purpose

Sprint 6 makes Course Courier operationally simple for a course that publishes from a private repository to a public repository. Once a maintainer has configured the environment and token, a push to protected private `main` automatically rebuilds, verifies, compares, and synchronizes the public export. No pull request, pasted manifest hash, or manual publish dispatch is part of the normal workflow.

This specification records the completed integration for `olearydj/INSY7130-Py4PDTS` and `olearydj/INSY7130`.

## Workflow contract

The private repository contains one workflow, `.github/workflows/course-courier-publish.yml`. It runs on pushes to `main` that change `content/**`; this includes the manifest at `content/PUBLISH.toml`. A `workflow_dispatch` trigger remains available for a no-change operational check.

The workflow uses the `public-course-publish` GitHub Environment. That environment restricts deployment to private `main` and provides `COURSE_COURIER_PUBLIC_TOKEN` as an environment secret. The fine-grained token has repository contents read/write access to the public destination repository only.

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
  group: public-course-publish-7130-main
  cancel-in-progress: false

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

## Publication behavior

The publish Action invokes `ccc build` and `ccc verify` with the locked Course Courier environment. It derives the public repository, branch, and managed boundary exclusively from the verified manifest. It then compares the staged export with the public checkout.

When the trees differ, the Action mirrors the staged managed boundary, commits the change with the private source commit and manifest SHA-256, and pushes to the manifest-selected public branch. When they match, it exits successfully without creating a commit. Every run uploads the inventory and pre-publish comparison as an artifact.

The course workflow deliberately omits `expected_manifest_sha256`. That optional Action input remains available for a separately reviewed, manually dispatched caller, but protected-branch synchronization rebuilds from the exact private commit that triggered the run.

## Safety boundaries

- Only private `main` can trigger automatic publication.
- Only changes under `content/` trigger it; unrelated repository edits do not publish content.
- The public destination and writable subtree come only from `PUBLISH.toml` after validation.
- The environment-scoped token is rejected if empty and is not available outside the `public-course-publish` job.
- The token is scoped to the public destination repository, not the private source repository.
- The workflow has read-only default permissions for the source repository and serializes publishes with a concurrency group.
- A valid build and verification are required before the Action can change the public checkout.
- A no-difference result is a successful no-op.

## Operational procedure

1. Edit private course material or `content/PUBLISH.toml`.
2. Commit and push the change to private `main`.
3. Open the resulting `Publish course export` Actions run if confirmation is needed.
4. Inspect the public repository or the run artifact when diagnosing an unexpected result.

## Retrospective verification

The workflow was verified with a real push that added a temporary TOML comment to `content/PUBLISH.toml`. GitHub Actions triggered the publish workflow, rebuilt and verified the export, and made no public commit because the staged content bytes were unchanged. A second push removed the comment and completed the same no-op path. The public repository remained at its existing publication commit throughout the test.

## Definition of done

Sprint 6 is complete when the private repository has the protected-branch automatic workflow, the environment secret is configured with least privilege, a real push has exercised the workflow, unchanged exports create no public commit, and the normal maintainer experience is only edit, commit, and push.
