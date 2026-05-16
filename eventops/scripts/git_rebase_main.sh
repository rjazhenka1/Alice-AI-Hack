#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

REMOTE="${REMOTE:-origin}"
BASE_BRANCH="${BASE_BRANCH:-main}"
CURRENT_BRANCH="$(git branch --show-current)"

echo "Repository: $REPO_ROOT"
echo "Current branch: $CURRENT_BRANCH"
echo "Base: $REMOTE/$BASE_BRANCH"
echo

if [[ -z "$CURRENT_BRANCH" ]]; then
  echo "Detached HEAD. Refusing to rebase."
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  echo "Working tree is not clean. Commit, stash, or restore changes first."
  echo
  git status --short --branch --untracked-files=all
  exit 1
fi

git fetch "$REMOTE"
git rebase "$REMOTE/$BASE_BRANCH"
echo
git status --short --branch --untracked-files=all

