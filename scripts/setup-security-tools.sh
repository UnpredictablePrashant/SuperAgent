#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="$ROOT_DIR/config"
CONFIG_FILE="$CONFIG_DIR/security-tools.env"
CONFIG_TEMPLATE="$CONFIG_DIR/security-tools.env.example"
AUTO_INSTALL=false

for arg in "$@"; do
  case "$arg" in
    --auto-install) AUTO_INSTALL=true ;;
  esac
done

BOLD='\033[1m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; CYAN='\033[36m'; RESET='\033[0m'
info() { echo -e "${CYAN}▸${RESET} $*"; }
ok() { echo -e "${GREEN}✔${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*"; }
err() { echo -e "${RED}✘${RESET} $*"; }

has_cmd() { command -v "$1" >/dev/null 2>&1; }
run_install_cmd() {
  local cmd="$1"
  if eval "$cmd"; then
    return 0
  fi
  return 1
}

mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_FILE" ]]; then
  info "Creating default config at $CONFIG_FILE"
  if [[ -f "$CONFIG_TEMPLATE" ]]; then
    cp "$CONFIG_TEMPLATE" "$CONFIG_FILE"
  else
    cat > "$CONFIG_FILE" <<'CFG'
# Security tooling defaults
# Toggle to true only for assets you own or have explicit written authorization to test.
SECURITY_SCAN_AUTHORIZED=false
SECURITY_AUTHORIZATION_NOTE=""

# Tool toggles
ENABLE_NMAP=true
ENABLE_ZAP=true
USE_DOCKER_ZAP=true

# Scan tuning
SCAN_PROFILE=quick
NMAP_TOP_PORTS=1000
ZAP_SPIDER_MINS=2
ZAP_MAX_DURATION_MINS=5

# Output
SECURITY_SCAN_OUTPUT_DIR=output/security-scans
CFG
  fi
  ok "Default config created"
else
  ok "Config already exists at $CONFIG_FILE"
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
info "Detected OS: $OS"
info "Auto install: $AUTO_INSTALL"

install_nmap() {
  if has_cmd nmap; then
    ok "nmap already installed"
    return 0
  fi
  if [[ "$AUTO_INSTALL" != "true" ]]; then
    warn "nmap missing (rerun with --auto-install to attempt install)"
    return 1
  fi

  info "Attempting nmap install"
  if has_cmd apt-get; then
    run_install_cmd "sudo apt-get update && sudo apt-get install -y nmap" && ok "nmap installed via apt-get" && return 0
  elif has_cmd dnf; then
    run_install_cmd "sudo dnf install -y nmap" && ok "nmap installed via dnf" && return 0
  elif has_cmd yum; then
    run_install_cmd "sudo yum install -y nmap" && ok "nmap installed via yum" && return 0
  elif has_cmd pacman; then
    run_install_cmd "sudo pacman -Sy --noconfirm nmap" && ok "nmap installed via pacman" && return 0
  elif has_cmd brew; then
    run_install_cmd "brew install nmap" && ok "nmap installed via brew" && return 0
  fi

  err "Could not auto-install nmap. Install manually and rerun preflight."
  return 1
}

install_zap() {
  if has_cmd zap-baseline.py || has_cmd owasp-zap; then
    ok "OWASP ZAP already installed"
    return 0
  fi
  if [[ "${USE_DOCKER_ZAP:-true}" == "true" ]] && has_cmd docker; then
    ok "Docker available: OWASP ZAP can run via docker image"
    return 0
  fi
  if [[ "$AUTO_INSTALL" != "true" ]]; then
    warn "OWASP ZAP missing (rerun with --auto-install to attempt install)"
    return 1
  fi

  info "Attempting OWASP ZAP install"
  if has_cmd apt-get; then
    run_install_cmd "sudo apt-get update && sudo apt-get install -y zaproxy" && ok "OWASP ZAP installed via apt-get" && return 0
  elif has_cmd brew; then
    run_install_cmd "brew install --cask owasp-zap" && ok "OWASP ZAP installed via brew cask" && return 0
  fi

  err "Could not auto-install OWASP ZAP. Install manually or enable docker fallback."
  return 1
}

install_nmap || true
install_zap || true

echo
info "Running preflight..."
"$ROOT_DIR/scripts/preflight-security-tools.sh"

echo
ok "Security setup finished"
echo "Next:"
echo "  1) Edit $CONFIG_FILE and set SECURITY_SCAN_AUTHORIZED=true"
echo "  2) Run ./scripts/scan-website.sh https://example.com"
