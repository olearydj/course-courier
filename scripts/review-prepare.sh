#!/usr/bin/env bash
set -euo pipefail

review_root="${RUNNER_TEMP}/course-courier-review"
stage="${review_root}/stage"
inventory="${review_root}/inventory.json"
review="${review_root}/review.json"

mkdir -p "${review_root}"
uv run --locked --project "${GITHUB_ACTION_PATH}" ccc build --config "${GITHUB_WORKSPACE}/${CONFIG}" --output "${stage}" > "${inventory}"
uv run --locked --project "${GITHUB_ACTION_PATH}" ccc verify --config "${GITHUB_WORKSPACE}/${CONFIG}" --output "${stage}" > "${review_root}/verify.json"
cmp -s "${inventory}" "${review_root}/verify.json"
uv run --locked --project "${GITHUB_ACTION_PATH}" python - "${inventory}" >> "${GITHUB_OUTPUT}" <<'PY'
import json
import sys

inventory = json.load(open(sys.argv[1]))
print(f"repository={inventory['public']['repository']}")
print(f"branch={inventory['public']['branch']}")
print(f"managed_subtree={inventory['public']['managed_subtree']}")
PY
printf 'inventory=%s\nreview=%s\nstage=%s\n' "${inventory}" "${review}" "${stage}" >> "${GITHUB_OUTPUT}"
