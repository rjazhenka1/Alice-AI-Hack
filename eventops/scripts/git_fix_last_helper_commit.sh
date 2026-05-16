#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

TARGET="eventops/backend/.env.example"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Working tree has tracked changes. Commit or restore them before amending."
  git status --short --branch --untracked-files=all
  exit 1
fi

echo "Restoring $TARGET in HEAD to the version from HEAD^"
git restore --source=HEAD^ --staged --worktree -- "$TARGET"
git add "$TARGET"

echo "Amending last commit without backend env example noise..."
git commit --amend --no-edit
echo
git show --stat --oneline --name-status HEAD

