#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

MESSAGE="${1:-update frontend}"
PATHS=("eventops/frontend" "eventops/scripts")

echo "Repository: $REPO_ROOT"
echo "Commit message: $MESSAGE"
echo

if ! git diff --quiet -- "${PATHS[@]}" || ! git diff --cached --quiet -- "${PATHS[@]}" || [[ -n "$(git ls-files --others --exclude-standard -- "${PATHS[@]}")" ]]; then
  git add "${PATHS[@]}"
else
  echo "No frontend/script changes to commit."
  exit 0
fi

echo "Staged frontend/script changes:"
git diff --cached --stat -- "${PATHS[@]}"
echo

git commit -m "$MESSAGE"
echo
git status --short --branch --untracked-files=all

