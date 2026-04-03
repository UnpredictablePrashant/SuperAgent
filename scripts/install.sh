#!/usr/bin/env bash
# kendr install script — Linux / macOS
# Usage:
#   ./scripts/install.sh           # core install (OpenAI)
#   ./scripts/install.sh --full    # all optional providers
set -euo pipefail

KENDR_VERSION="0.2.0"
FULL_INSTALL=0
for arg in "$@"; do
  [[ "$arg" == "--full" ]] && FULL_INSTALL=1
done

BOLD='\033[1m'; TEAL='\033[36m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'

banner() { echo -e "\n${TEAL}${BOLD}  ⚡ kendr v${KENDR_VERSION} installer${RESET}\n"; }
info()   { echo -e "  ${TEAL}▸${RESET} $*"; }
ok()     { echo -e "  ${GREEN}✔${RESET} $*"; }
warn()   { echo -e "  ${YELLOW}⚠${RESET} $*"; }
die()    { echo -e "\n  ${RED}✘ ERROR:${RESET} $*\n" >&2; exit 1; }

banner

# ── 1. Python check ─────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  die "Python 3.10+ is required but was not found.\n  → Install from https://python.org/downloads\n  → Or via Homebrew: brew install python"
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
  die "Python 3.10+ is required. Found: Python $PY_VER\n  → Install a newer version from https://python.org/downloads"
fi
ok "Python $PY_VER detected"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# ── 2. Virtual environment ───────────────────────────────────────────────────
create_venv() {
  info "Creating virtual environment..."
  python3 -m venv .venv
}

if [ ! -d ".venv" ]; then
  create_venv
elif [ -d ".venv/Scripts" ] && [ ! -e ".venv/bin/python" ]; then
  warn "Existing .venv was created by Windows Python and cannot be used from bash."
  info "Recreating virtual environment for this shell..."
  rm -rf .venv
  create_venv
fi
ok "Virtual environment ready"

VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
VENV_BIN="$ROOT_DIR/.venv/bin"

if [ ! -e "$VENV_PYTHON" ]; then
  die "Virtual environment is missing $VENV_PYTHON\n  → Delete .venv and rerun ./scripts/install.sh"
fi

# ── 3. Upgrade pip ───────────────────────────────────────────────────────────
info "Upgrading pip..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet
ok "pip up to date"

# ── 4. Install kendr ─────────────────────────────────────────────────────────
if [[ "$FULL_INSTALL" -eq 1 ]]; then
  info "Installing kendr with all optional providers..."
  "$VENV_PYTHON" -m pip install -e ".[full]" --quiet
  ok "kendr installed (full — all providers)"
else
  info "Installing kendr (core + OpenAI)..."
  "$VENV_PYTHON" -m pip install -e "." --quiet
  ok "kendr installed"
  echo ""
  echo -e "  ${YELLOW}Add more LLM providers any time:${RESET}"
  echo -e "    ${TEAL}.venv/bin/pip install 'kendr-runtime[anthropic]'${RESET}  — Anthropic Claude"
  echo -e "    ${TEAL}.venv/bin/pip install 'kendr-runtime[google]'${RESET}     — Google Gemini"
  echo -e "    ${TEAL}.venv/bin/pip install 'kendr-runtime[ollama]'${RESET}     — Local Ollama"
  echo -e "    ${TEAL}.venv/bin/pip install 'kendr-runtime[full]'${RESET}       — All of the above"
fi

# ── 5. Bootstrap runtime state ───────────────────────────────────────────────
if [ -f "scripts/bootstrap_local_state.py" ]; then
  info "Bootstrapping runtime state..."
  "$VENV_PYTHON" scripts/bootstrap_local_state.py 2>/dev/null && ok "Runtime state ready" || warn "Bootstrap skipped (non-fatal)"
fi

# ── 6. Add .venv/bin to PATH ─────────────────────────────────────────────────
SHELL_NAME="$(basename "${SHELL:-bash}")"
if [[ "$SHELL_NAME" == "zsh" ]]; then
  RC_FILE="$HOME/.zshrc"
else
  RC_FILE="$HOME/.bashrc"
fi

PATH_LINE="export PATH=\"$VENV_BIN:\$PATH\""
if [ -f "$RC_FILE" ] && grep -qF "$VENV_BIN" "$RC_FILE" 2>/dev/null; then
  ok "PATH already configured in $(basename "$RC_FILE")"
else
  printf '\n# kendr\n%s\n' "$PATH_LINE" >> "$RC_FILE"
  ok "Added kendr to PATH in $RC_FILE"
fi

[[ ":$PATH:" != *":$VENV_BIN:"* ]] && export PATH="$VENV_BIN:$PATH"

# ── 7. Done ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}  ✔ kendr v${KENDR_VERSION} is ready!${RESET}"
echo ""
echo -e "  ${BOLD}Next steps:${RESET}"
echo -e "  1. Reload your shell:     ${TEAL}source $RC_FILE${RESET}"
echo -e "  2. Set your API key:      ${TEAL}kendr setup set openai OPENAI_API_KEY sk-...${RESET}"
echo -e "  3. Set your working dir:  ${TEAL}kendr setup set core_runtime KENDR_WORKING_DIR ~/kendr-work${RESET}"
echo -e "  4. Launch the Web UI:     ${TEAL}kendr ui${RESET}"
echo -e "     Or run a CLI query:    ${TEAL}kendr run \"summarise the AI chip market\"${RESET}"
echo ""
echo -e "  Docs → ${TEAL}https://github.com/kendr-ai/kendr/blob/main/docs/quickstart.md${RESET}"
echo ""
