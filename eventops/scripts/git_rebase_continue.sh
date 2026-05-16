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

CONFLICTS="$(git diff --name-only --diff-filter=U || true)"
if [[ -n "$CONFLICTS" ]]; then
  echo "There are still unresolved conflicts:"
  echo "$CONFLICTS"
  echo
  echo "Resolve them and git add the fixed files, then rerun this script."
  exit 1
fi

if [[ -n "$(git diff --name-only)" ]]; then
  echo "You have unstaged changes. Stage resolved files before continuing:"
  git status --short --branch --untracked-files=all
  exit 1
fi

echo "Continuing rebase..."
if GIT_EDITOR=true git rebase --continue; then
  echo
  echo "Rebase step completed."
  git status --short --branch --untracked-files=all
  if [[ -d .git/rebase-merge || -d .git/rebase-apply ]]; then
    echo
    echo "More rebase steps remain. If conflicts appear, fix and rerun this script."
  else
    echo
    echo "Rebase finished. Run push when ready:"
    echo "  eventops/scripts/git_push_frontend.sh"
  fi
else
  echo
  echo "Rebase stopped again. Conflicted files:"
  git diff --name-only --diff-filter=U || true
  exit 1
fi
