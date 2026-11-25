#!/usr/bin/env bash
# Push a scheduled job's data commit to main with a docs-sync status on it.
#
# main requires the `docs-sync` check, and docs-sync.yml only runs on pull
# requests, so a job's plain `git push` to main is rejected (GH013). This runs
# the same checker on the job's own commit, records its verdict as the
# `docs-sync` commit status, and only then pushes that commit to main. A data
# commit that the checker would fail is never pushed.
#
# Usage: scripts/push_to_main.sh NAME
#   NAME     names the scratch branch bot/NAME the commit is staged on, so the
#            status can be attached before main sees it.
# Needs GH_TOKEN (the job's token, with `statuses: write` and `contents: write`)
# and the commit to push at HEAD, one commit on top of the checked-out
# $GITHUB_SHA. Exits 0 when there is nothing new to push.
#
# DOCS_SYNC_CMD overrides the checker command (tests only).
set -euo pipefail

name="${1:?usage: push_to_main.sh NAME}"
target="${GITHUB_REF_NAME:-main}"
scratch="bot/${name}"
start="${GITHUB_SHA:?GITHUB_SHA is not set}"
check_cmd="${DOCS_SYNC_CMD:-python3 tools/check_docs_sync.py}"
run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is not set}/actions/runs/${GITHUB_RUN_ID:-0}"

data_commit="$(git rev-parse HEAD)"
if [ "$data_commit" = "$(git rev-parse "$start")" ]; then
  echo "Nothing new to push."
  exit 0
fi

drop_scratch() {
  git push --quiet origin --delete "$scratch" 2>/dev/null || true
}

for attempt in 1 2 3; do
  git fetch --quiet origin "$target"
  tip="$(git rev-parse "origin/$target")"

  # Replay the data commit on the current tip of main.
  git checkout --quiet --detach "$tip"
  if ! git cherry-pick --keep-redundant-commits "$data_commit" >/dev/null; then
    git cherry-pick --abort || true
    echo "::error::The data commit conflicts with $target; not pushed." >&2
    exit 1
  fi
  if git diff --quiet "$tip" HEAD; then
    echo "$target already has this data."
    exit 0
  fi
  sha="$(git rev-parse HEAD)"

  # The status can only be set on a commit GitHub already has.
  git push --quiet --force origin "HEAD:refs/heads/$scratch"
  if $check_cmd --base "$tip" --head "$sha"; then
    state=success
    description="docs-sync passed on this ${GITHUB_WORKFLOW:-scheduled} commit"
  else
    state=failure
    description="docs-sync failed on this ${GITHUB_WORKFLOW:-scheduled} commit"
  fi
  gh api --silent -X POST "repos/$GITHUB_REPOSITORY/statuses/$sha" \
    -f state="$state" -f context=docs-sync \
    -f description="${description:0:140}" -f target_url="$run_url"
  if [ "$state" != success ]; then
    drop_scratch
    echo "::error::docs-sync failed on the data commit; not pushed to $target." >&2
    exit 1
  fi

  if git push --quiet origin "HEAD:$target"; then
    drop_scratch
    echo "Pushed $sha to $target (attempt $attempt)."
    exit 0
  fi
  echo "$target moved or rejected the push; retrying."
done

drop_scratch
echo "::error::Could not push the data commit to $target after 3 attempts." >&2
exit 1
