#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

TARGET="eventops/backend/.env.example"
SOURCE_REF="${SOURCE_REF:-origin/main}"

echo "Restoring $TARGET from $SOURCE_REF"
git restore --source="$SOURCE_REF" --staged --worktree -- "$TARGET"
echo
git status --short --branch --untracked-files=all
