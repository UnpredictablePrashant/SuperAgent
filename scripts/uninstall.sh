#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SCRIPT_DIR="$ROOT_DIR/.venv/bin"

if [ -x ".venv/bin/python" ]; then
  echo "[uninstall] uninstalling superagent-runtime from .venv"
  .venv/bin/python -m pip uninstall -y superagent-runtime >/dev/null 2>&1 || true
else
  echo "[uninstall] .venv not found; skipping package uninstall"
fi

SHELL_NAME="$(basename "${SHELL:-}")"
if [ "$SHELL_NAME" = "zsh" ]; then
  RC_FILE="$HOME/.zshrc"
else
  RC_FILE="$HOME/.bashrc"
fi

if [ -f "$RC_FILE" ] && grep -F "$SCRIPT_DIR" "$RC_FILE" >/dev/null 2>&1; then
  TMP_FILE="$(mktemp)"
  grep -Fv "$SCRIPT_DIR" "$RC_FILE" > "$TMP_FILE" || true
  mv "$TMP_FILE" "$RC_FILE"
  echo "[uninstall] removed PATH entry from $RC_FILE"
else
  echo "[uninstall] no PATH entry found in $RC_FILE"
fi

if [ -d ".venv" ]; then
  rm -rf .venv
  echo "[uninstall] removed .venv"
else
  echo "[uninstall] .venv already removed"
fi

echo "[uninstall] done"
echo "[uninstall] reload shell config: source $RC_FILE"
