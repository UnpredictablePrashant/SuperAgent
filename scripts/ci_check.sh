#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export OPENAI_API_KEY="${OPENAI_API_KEY:-test-openai-key}"
export PYTHONPATH="${PYTHONPATH:-.}"

echo "[ci] compileall"
python3 scripts/verify.py compile unit smoke docs docker --strict-docker

echo "[ci] ok"
