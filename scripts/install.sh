#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "[install] creating .venv"
  python3 -m venv .venv
fi

echo "[install] upgrading pip"
.venv/bin/python -m pip install --upgrade pip

echo "[install] installing package"
.venv/bin/python -m pip install -e .

SCRIPT_DIR="$ROOT_DIR/.venv/bin"

SHELL_NAME="$(basename "${SHELL:-}")"
if [ "$SHELL_NAME" = "zsh" ]; then
  RC_FILE="$HOME/.zshrc"
else
  RC_FILE="$HOME/.bashrc"
fi

PATH_LINE="export PATH=\"$SCRIPT_DIR:\$PATH\""
if [ -f "$RC_FILE" ] && grep -F "$SCRIPT_DIR" "$RC_FILE" >/dev/null 2>&1; then
  echo "[install] PATH already configured in $RC_FILE"
else
  echo "$PATH_LINE" >> "$RC_FILE"
  echo "[install] added $SCRIPT_DIR to PATH in $RC_FILE"
fi

if [[ ":$PATH:" != *":$SCRIPT_DIR:"* ]]; then
  export PATH="$SCRIPT_DIR:$PATH"
fi

echo "[install] done"
echo "[install] run: source $RC_FILE"
echo "[install] then verify: superagent --help"
