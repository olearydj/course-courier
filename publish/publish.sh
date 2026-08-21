#!/usr/bin/env bash
set -euo pipefail

public_root="${GITHUB_WORKSPACE}/.course-courier-public"
if [ "${MANAGED_SUBTREE}" = "." ]; then
  stage_boundary="${STAGE}"
  public_boundary="${public_root}"
else
  stage_boundary="${STAGE}/${MANAGED_SUBTREE}"
  public_boundary="${public_root}/${MANAGED_SUBTREE}"
fi

uv run --locked --project "${GITHUB_ACTION_PATH}/.." python -m course_courier.review --stage "${STAGE}" --public "${public_root}" --managed-subtree "${MANAGED_SUBTREE}" > "${REVIEW}"
changed="$(uv run --locked --project "${GITHUB_ACTION_PATH}/.." python - "${REVIEW}" <<'PY'
import json
import sys

print(str(json.load(open(sys.argv[1]))["changed"]).lower())
PY
)"
if [ "${changed}" = "false" ]; then
  printf 'published=false\n' >> "${GITHUB_OUTPUT}"
  exit 0
fi

if [ "${MANAGED_SUBTREE}" != "." ]; then
  mkdir -p "${public_boundary}"
fi
rsync -a --delete --exclude=.git "${stage_boundary}/" "${public_boundary}/"
git -C "${public_root}" config user.name "course-courier[bot]"
git -C "${public_root}" config user.email "course-courier[bot]@users.noreply.github.com"
git -C "${public_root}" add -A
if [ -z "$(git -C "${public_root}" status --porcelain)" ]; then
  echo "Course Courier review reported a change, but mirroring left the public checkout Git-clean." >&2
  exit 1
fi
commit_message="Publish course content from ${GITHUB_SHA} (manifest ${MANIFEST_SHA256})"
if [ -n "${RELEASE_MANIFEST_SHA256:-}" ]; then
  commit_message="${commit_message} (release list ${RELEASE_MANIFEST_SHA256})"
fi
git -C "${public_root}" commit -m "${commit_message}"
git -C "${public_root}" push origin "HEAD:${BRANCH}"
printf 'published=true\n' >> "${GITHUB_OUTPUT}"
