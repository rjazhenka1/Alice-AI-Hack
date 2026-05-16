#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "== compose ps =="
docker compose ps
echo

echo "== backend health from host =="
curl -i --max-time 5 http://localhost:8000/health || true
echo

echo "== frontend from host =="
curl -I --max-time 5 http://localhost:5173 || true
echo

echo "== backend logs =="
docker compose logs --tail=180 backend || true
echo

echo "== frontend logs =="
docker compose logs --tail=120 frontend || true

