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
uv run --locked --project "${GITHUB_ACTION_PATH}/.." python - "${inventory}" "${EXPECTED_MANIFEST_SHA256}" >> "${GITHUB_OUTPUT}" <<'PY'
import json
import sys

inventory = json.load(open(sys.argv[1]))
if sys.argv[2] and inventory["manifest_sha256"] != sys.argv[2]:
    raise SystemExit("reviewed manifest SHA-256 does not match the current manifest")
print(f"repository={inventory['public']['repository']}")
print(f"branch={inventory['public']['branch']}")
print(f"managed_subtree={inventory['public']['managed_subtree']}")
print(f"manifest_sha256={inventory['manifest_sha256']}")
PY
printf 'inventory=%s\nreview=%s\nstage=%s\n' "${inventory}" "${review}" "${stage}" >> "${GITHUB_OUTPUT}"
