#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

REMOTE="${REMOTE:-origin}"
BASE_BRANCH="${BASE_BRANCH:-main}"
WORK_BRANCH="${WORK_BRANCH:-frontend}"
CURRENT_BRANCH="$(git branch --show-current)"

show_conflicts() {
  echo
  echo "Conflicted files:"
  git diff --name-only --diff-filter=U || true
  echo
  echo "Fix conflicts, then run:"
  echo "  eventops/scripts/git_rebase_continue.sh"
  echo
  echo "To abort this rebase:"
  echo "  eventops/scripts/git_abort_rebase.sh"
}

echo "Repository: $REPO_ROOT"
echo "Remote/base: $REMOTE/$BASE_BRANCH"
echo "Work branch: $WORK_BRANCH"
echo "Current branch: $CURRENT_BRANCH"
echo

if [[ -z "$CURRENT_BRANCH" ]]; then
  echo "Detached HEAD. Refusing to continue."
  exit 1
fi

if [[ -d .git/rebase-merge || -d .git/rebase-apply ]]; then
  echo "A rebase is already in progress."
  show_conflicts
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  echo "Working tree is not clean. Commit or stash changes before syncing."
  echo
  git status --short --branch --untracked-files=all
  exit 1
fi

if [[ "$CURRENT_BRANCH" != "$WORK_BRANCH" ]]; then
  echo "Switching to $WORK_BRANCH"
  git switch "$WORK_BRANCH"
fi

echo "Fetching $REMOTE..."
git fetch "$REMOTE" --prune

echo
echo "Rebasing $WORK_BRANCH onto $REMOTE/$BASE_BRANCH..."
if git rebase "$REMOTE/$BASE_BRANCH"; then
  echo
  echo "Rebase completed. Current status:"
  git status --short --branch --untracked-files=all
  echo
  echo "Run push when ready:"
  echo "  eventops/scripts/git_push_frontend.sh"
else
  echo
  echo "Rebase stopped because of conflicts."
  show_conflicts
  exit 1
fi
