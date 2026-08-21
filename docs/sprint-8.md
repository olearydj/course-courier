# Course Courier — Sprint 8 specification

## Purpose

Sprint 8 adds one scaffolding command, `ccc init-workflow`, that writes a course repository's publish workflow with correct, immutable action pins. The workflow file is the one setup artifact where hand-copying reliably fails: its two commit-SHA pins must be exact and current, and its trigger paths, config path, and concurrency group must agree with the course's actual layout. Generating the file makes those properties mechanical, keeps every course's workflow consistent, and turns future Course Courier upgrades into a re-run instead of per-course hand edits.

The command is deliberately narrow. It writes exactly one local file and changes nothing else; the GitHub Environment, token, secret, and branch protection remain manual steps that the command lists but never performs.

## Command contract

```text
ccc init-workflow --config content/PUBLISH.toml [--branch main] [--sha <40-hex>] [--force]
```

`--config` is required and names the course manifest, exactly as for `plan`. The command resolves the manifest with the same planner used by `plan`, so a workflow is only ever scaffolded for a configuration that currently validates and resolves; it works for version-1 and version-2 manifests alike. `--branch` names the private publishing branch, defaults to `main`, and is validated with the shared Sprint 6.5 Git branch-name rules before any rendering.

The command locates the Git work-tree root containing the manifest (`git rev-parse --show-toplevel` from the manifest's directory) and writes `.github/workflows/course-courier-publish.yml` at that root. Running outside a Git work tree is an error: the workflow is meaningless without one. The manifest and its resolved content root must both lie beneath the detected work-tree root, with no symbolic-link component escaping it; a manifest outside the work tree, or reachable only through such a link, is an error. In practice Git resolves symbolic links before locating a work tree, so an escaping manifest is normally rejected as being outside one; the explicit containment check remains as defense-in-depth for configurations where Git environment variables make work-tree detection disagree with the manifest's resolved location. The rendered `config` value is the canonical work-tree-relative POSIX path, so the generated workflow is correct for CI's checkout, not merely for the invoking shell's location.

If the workflow file already exists the command refuses and exits non-zero. `--force` overwrites it atomically: the complete workflow is rendered and validated first, written to a temporary sibling, and renamed over the existing file, so a failed or interrupted command never leaves a truncated or partial workflow behind. No other file is created, modified, or deleted, and the content root is never touched.

On success the command prints the written path and the remaining manual checklist to standard output: create the `public-course-publish` Environment restricted to the publishing branch, add the fine-grained token as `COURSE_COURIER_PUBLIC_TOKEN`, protect the publishing branch, and run the workflow once by hand before relying on pushes. Failures print a concise diagnostic to standard error and exit non-zero.

## Template contract

The generated workflow is the documented Sprint 6 shape with every variable element derived rather than hand-typed. Every dynamic scalar - branch, paths, config path, concurrency group - is emitted through YAML-safe serialization, never string interpolation into a template: a valid Git ref or filename can still contain YAML-significant characters, and the generated document must parse back to exactly the intended values.

- The `push` trigger names the `--branch` value, and its `paths` filter is the content root's canonical work-tree-relative POSIX path plus `/**`, so a non-standard content root gets a correct trigger instead of a copied `content/**`. When the content root is the work-tree root itself, the relative path is `.` and the filter is `**`, not the mechanical `./**`.
- The `config` input is the canonical work-tree-relative manifest path.
- The concurrency group is `public-course-publish-<repository>-<branch>`, where `<repository>` is the repository segment of `public.repository`, lowercased. `cancel-in-progress` is `false`.
- `permissions` is `contents: read`, the job uses the `public-course-publish` environment, and `workflow_dispatch` is retained.
- The `actions/checkout` step is pinned to the same immutable commit SHA the composite Actions pin internally, with its version comment.
- The `olearydj/course-courier/publish` step is pinned to the commit SHA of the running Course Courier release, with a `# v<version>` comment, resolved as specified below.

## Release pin resolution

The command cannot embed its own release commit SHA at build time, because that SHA does not exist until the release commit is made. It therefore resolves the pin at run time: `git ls-remote` against the official repository for its own version tag, reading the peeled `refs/tags/v<version>^{}` commit SHA, not the annotated tag object's SHA. The resolved value must be a 40-character hexadecimal commit identifier or the command fails.

Resolution presumes a released build: the installed package version must have a corresponding annotated `v<version>` tag in the official repository. An editable, locally modified, or development build has no such tag and fails resolution rather than being silently treated as a release; `--sha` is the deliberate override for that case as well as for offline or air-gapped use, and must itself be a 40-character hexadecimal value. When resolution fails (no network, unknown tag, Git unavailable), the command fails with a diagnostic that names the `--sha` escape hatch; it never writes a workflow with a placeholder, tag-ref, or branch-ref pin, since tags and branches are mutable and the calling workflow must be immutable.

The remote URL defaults to the official repository through an injectable internal resolver seam, so tests exercise real peeled-tag resolution against a local bare repository rather than mocking the subprocess. `init-workflow` is the only Course Courier command that touches the network, and only through this single `git ls-remote` invocation.

## Documentation

`docs/setup.md` step 6 becomes the command invocation, retaining the generated YAML as reference material so a maintainer can still review or hand-edit what the command produces. The retained reference uses `<immutable-SHA> # v<version>` placeholders rather than literal current pins, matching the earlier sprint documents, so the documentation cannot become a stale recommended pin; a test enforces that no literal Course Courier commit pin appears in the setup guide. The CHANGELOG records the new command. The command's `--help` text states what is written, what is resolved remotely, and what remains manual.

## Acceptance tests

- The generated workflow matches the documented template byte for byte given a fixture manifest, branch, and pinned SHAs, including the derived trigger paths, config path, and concurrency group.
- A version-1 and a version-2 fixture manifest both scaffold successfully; an invalid manifest fails before anything is written; an invalid `--branch` value fails with the shared branch-name diagnostic.
- A non-standard content root (not named `content`) yields matching `paths` and `config` values, and a manifest at the work-tree root yields `paths` of `**`, not `./**`.
- YAML-significant but valid branch and path values round-trip: the generated document parses back to exactly the intended scalar values.
- A manifest outside the detected work tree, or reachable only through a symbolic link escaping it, is rejected before anything is written.
- Pin resolution through the resolver seam against a local bare repository with an annotated tag returns the peeled commit SHA, not the tag object SHA.
- Failed resolution (unreachable remote, missing tag, or an unreleased development version) exits non-zero, names `--sha`, and writes nothing; a malformed `--sha` value is rejected.
- An existing workflow file is refused without `--force` and preserved byte for byte; `--force` replaces it atomically; a failure injected after rendering begins leaves the prior workflow intact; no other file in the work tree changes in any case.
- Running with a manifest outside a Git work tree fails with a clear diagnostic.
- The success output names the written path and every manual checklist item.
- The setup guide contains no literal Course Courier commit pin in its retained reference YAML.

## Non-goals

- No creation of GitHub Environments, secrets, tokens, or branch protection, and no invocation of `gh` or the GitHub API.
- No review-workflow scaffold; the review Action remains documented in `docs/sprint-4.md`.
- No modification of the manifest, release list, or any content; `init-workflow` is not a migration tool.
- No self-update or upgrade command; upgrading a course remains re-running `init-workflow --force` from a newer Course Courier release.

## Definition of done

Sprint 8 is complete when `ccc init-workflow` scaffolds the documented workflow with a verified immutable pin for the running release, serializes every dynamic value YAML-safely from validated inputs, confines itself to a manifest and content root beneath the work-tree root, refuses unsafe overwrites and replaces atomically under `--force`, fails closed when the pin cannot be resolved or the build is unreleased, prints the manual completion checklist, the setup guide uses the command as its workflow step with no literal pin in its reference material, and the acceptance tests pass alongside all earlier sprint tests.
