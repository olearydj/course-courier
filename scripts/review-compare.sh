#!/usr/bin/env bash
set -euo pipefail

public_root="${GITHUB_WORKSPACE}/.course-courier-public"
uv run --locked --project "${GITHUB_ACTION_PATH}" python -m course_courier.review --stage "${STAGE}" --public "${public_root}" --managed-subtree "${MANAGED_SUBTREE}" > "${REVIEW}"
uv run --locked --project "${GITHUB_ACTION_PATH}" python - "${REVIEW}" >> "${GITHUB_OUTPUT}" <<'PY'
import json
import sys

print(f"changed={str(json.load(open(sys.argv[1]))['changed']).lower()}")
PY
