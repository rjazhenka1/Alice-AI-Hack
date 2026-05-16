#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -d .git/rebase-merge && ! -d .git/rebase-apply ]]; then
  echo "No rebase in progress."
  git status --short --branch --untracked-files=all
  exit 0
fi

echo "Aborting rebase..."
git rebase --abort

git status --short --branch --untracked-files=all
