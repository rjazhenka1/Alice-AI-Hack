#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

echo "Repository: $REPO_ROOT"
echo

echo "Branch/status:"
git status --short --branch --untracked-files=all
echo

echo "Recent commits:"
git log --oneline --decorate --graph --max-count=12 --all
echo

echo ".git mount:"
if command -v findmnt >/dev/null 2>&1; then
  findmnt -T .git -o TARGET,OPTIONS || true
else
  echo "findmnt is not installed"
fi

