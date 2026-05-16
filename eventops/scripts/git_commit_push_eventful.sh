#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

MESSAGE="${1:-update eventful workflows}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-frontend}"
CURRENT_BRANCH="$(git branch --show-current)"

echo "Repository: $REPO_ROOT"
echo "Current branch: $CURRENT_BRANCH"
echo "Commit message: $MESSAGE"
echo

if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
  echo "Refusing to push: current branch is $CURRENT_BRANCH, expected $BRANCH."
  exit 1
fi

if [[ -d .git/rebase-merge || -d .git/rebase-apply ]]; then
  echo "Rebase is in progress. Finish or abort it before committing."
  exit 1
fi

git diff --check
git add eventops

echo "Staged changes:"
git diff --cached --stat
echo

if git diff --cached --quiet; then
  echo "Nothing staged; no commit created."
else
  git commit -m "$MESSAGE"
fi

echo
git status --short --branch --untracked-files=all
echo
git push "$REMOTE" "$BRANCH"
echo
git status --short --branch --untracked-files=all
