#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${SECURITY_TOOLS_CONFIG:-$ROOT_DIR/config/security-tools.env}"
CONFIG_TEMPLATE="$ROOT_DIR/config/security-tools.env.example"

if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
elif [[ -f "$CONFIG_TEMPLATE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_TEMPLATE"
fi

ENABLE_NMAP="${ENABLE_NMAP:-true}"
ENABLE_ZAP="${ENABLE_ZAP:-true}"
USE_DOCKER_ZAP="${USE_DOCKER_ZAP:-true}"

BOLD='\033[1m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; CYAN='\033[36m'; RESET='\033[0m'
info() { echo -e "${CYAN}▸${RESET} $*"; }
ok() { echo -e "${GREEN}✔${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*"; }
err() { echo -e "${RED}✘${RESET} $*"; }

has_cmd() { command -v "$1" >/dev/null 2>&1; }

missing=0

echo -e "${BOLD}Security Tools Preflight${RESET}"
info "Config file: $CONFIG_FILE"

if has_cmd nmap; then
  ok "nmap detected: $(nmap --version 2>/dev/null | head -n1 || echo nmap)"
else
  if [[ "$ENABLE_NMAP" == "true" ]]; then
    err "nmap missing"
    missing=1
  else
    warn "nmap missing (disabled via ENABLE_NMAP=false)"
  fi
fi

if has_cmd zap-baseline.py; then
  ok "zap-baseline.py detected"
elif has_cmd owasp-zap; then
  ok "owasp-zap detected"
elif [[ "$USE_DOCKER_ZAP" == "true" ]] && has_cmd docker; then
  ok "Docker detected: ZAP will run through docker image"
else
  if [[ "$ENABLE_ZAP" == "true" ]]; then
    err "OWASP ZAP missing (need zap-baseline.py, owasp-zap, or docker with USE_DOCKER_ZAP=true)"
    missing=1
  else
    warn "OWASP ZAP missing (disabled via ENABLE_ZAP=false)"
  fi
fi

if has_cmd curl; then
  ok "curl detected"
else
  warn "curl missing (recommended for URL checks)"
fi

if has_cmd python3; then
  ok "python3 detected"
else
  warn "python3 missing (some scanners and wrappers may fail)"
fi

if [[ "$missing" -ne 0 ]]; then
  echo
  err "Preflight failed. Run: ./scripts/setup-security-tools.sh --auto-install"
  exit 1
fi

echo
ok "Preflight passed"
