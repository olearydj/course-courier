#!/usr/bin/env bash
set -euo pipefail

test -n "${PUBLIC_TOKEN}"
test "${CONFIRMATION}" = "publish"

publish_root="${RUNNER_TEMP}/course-courier-publish"
stage="${publish_root}/stage"
inventory="${publish_root}/inventory.json"
review="${publish_root}/review.json"

mkdir -p "${publish_root}"
uv run --locked --project "${GITHUB_ACTION_PATH}/.." ccc build --config "${GITHUB_WORKSPACE}/${CONFIG}" --output "${stage}" > "${inventory}"
uv run --locked --project "${GITHUB_ACTION_PATH}/.." ccc verify --config "${GITHUB_WORKSPACE}/${CONFIG}" --output "${stage}" > "${publish_root}/verify.json"
cmp -s "${inventory}" "${publish_root}/verify.json"
uv run --locked --project "${GITHUB_ACTION_PATH}/.." python - "${inventory}" "${EXPECTED_MANIFEST_SHA256}" "${EXPECTED_RELEASE_MANIFEST_SHA256:-}" >> "${GITHUB_OUTPUT}" <<'PY'
import json
import sys

inventory = json.load(open(sys.argv[1]))
expected_manifest = sys.argv[2]
expected_release = sys.argv[3]
release_sha256 = inventory.get("release_manifest_sha256") or ""
if release_sha256:
    if bool(expected_manifest) != bool(expected_release):
        raise SystemExit(
            "a version-2 manifest requires expected_manifest_sha256 and"
            " expected_release_manifest_sha256 together or not at all"
        )
elif expected_release:
    raise SystemExit("expected_release_manifest_sha256 applies only to a version-2 manifest")
if expected_manifest and inventory["manifest_sha256"] != expected_manifest:
    raise SystemExit("reviewed manifest SHA-256 does not match the current manifest")
if expected_release and release_sha256 != expected_release:
    raise SystemExit("reviewed release-list SHA-256 does not match the current release list")
print(f"repository={inventory['public']['repository']}")
print(f"branch={inventory['public']['branch']}")
print(f"managed_subtree={inventory['public']['managed_subtree']}")
print(f"manifest_sha256={inventory['manifest_sha256']}")
print(f"release_manifest_sha256={release_sha256}")
PY
printf 'inventory=%s\nreview=%s\nstage=%s\n' "${inventory}" "${review}" "${stage}" >> "${GITHUB_OUTPUT}"
