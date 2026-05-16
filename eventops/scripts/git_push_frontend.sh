#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

REMOTE="${REMOTE:-origin}"
WORK_BRANCH="${WORK_BRANCH:-frontend}"
CURRENT_BRANCH="$(git branch --show-current)"

echo "Repository: $REPO_ROOT"
echo "Current branch: $CURRENT_BRANCH"
echo "Target: $REMOTE/$WORK_BRANCH"
echo

if [[ "$CURRENT_BRANCH" != "$WORK_BRANCH" ]]; then
  echo "Refusing to push: current branch is $CURRENT_BRANCH, expected $WORK_BRANCH."
  exit 1
fi

if [[ -d .git/rebase-merge || -d .git/rebase-apply ]]; then
  echo "Rebase is still in progress. Finish or abort it before pushing."
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  echo "Working tree is not clean. Commit or restore changes before pushing."
  echo
  git status --short --branch --untracked-files=all
  exit 1
fi

git push "$REMOTE" "$WORK_BRANCH"

echo
git status --short --branch --untracked-files=all
