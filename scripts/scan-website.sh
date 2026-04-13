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
SCAN_PROFILE="${SCAN_PROFILE:-quick}"
NMAP_TOP_PORTS="${NMAP_TOP_PORTS:-1000}"
ZAP_SPIDER_MINS="${ZAP_SPIDER_MINS:-2}"
ZAP_MAX_DURATION_MINS="${ZAP_MAX_DURATION_MINS:-5}"
SECURITY_SCAN_AUTHORIZED="${SECURITY_SCAN_AUTHORIZED:-false}"
SECURITY_AUTHORIZATION_NOTE="${SECURITY_AUTHORIZATION_NOTE:-}"
SECURITY_SCAN_OUTPUT_DIR="${SECURITY_SCAN_OUTPUT_DIR:-output/security-scans}"

BOLD='\033[1m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; CYAN='\033[36m'; RESET='\033[0m'
info() { echo -e "${CYAN}▸${RESET} $*"; }
ok() { echo -e "${GREEN}✔${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*"; }
err() { echo -e "${RED}✘${RESET} $*"; }

usage() {
  echo "Usage: $0 <target-url>"
  echo "Example: $0 https://example.com"
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

TARGET_URL="$1"
if [[ ! "$TARGET_URL" =~ ^https?:// ]]; then
  err "Target must start with http:// or https://"
  exit 1
fi

if [[ "$SECURITY_SCAN_AUTHORIZED" != "true" ]]; then
  err "Scan blocked: SECURITY_SCAN_AUTHORIZED=false in $CONFIG_FILE"
  echo "Set SECURITY_SCAN_AUTHORIZED=true only for authorized targets."
  exit 1
fi

if [[ -z "$SECURITY_AUTHORIZATION_NOTE" ]]; then
  warn "SECURITY_AUTHORIZATION_NOTE is empty. Consider documenting approval."
fi

"$ROOT_DIR/scripts/preflight-security-tools.sh"

host="${TARGET_URL#http://}"
host="${host#https://}"
host="${host%%/*}"
host="${host%%:*}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
out_dir="$ROOT_DIR/$SECURITY_SCAN_OUTPUT_DIR/${host}_${timestamp}"
mkdir -p "$out_dir"

info "Target: $TARGET_URL"
info "Output: $out_dir"
info "Profile: $SCAN_PROFILE"

if [[ "$SCAN_PROFILE" == "deep" ]]; then
  nmap_args="-sV -Pn"
  zap_quick_opts=""
else
  nmap_args="-sV -F -Pn"
  zap_quick_opts="-I"
fi

if [[ "$ENABLE_NMAP" == "true" ]]; then
  if command -v nmap >/dev/null 2>&1; then
    info "Running nmap"
    nmap $nmap_args --top-ports "$NMAP_TOP_PORTS" "$host" -oN "$out_dir/nmap.txt" > "$out_dir/nmap.stdout.log" 2>&1 || warn "nmap scan returned non-zero status"
    ok "nmap output: $out_dir/nmap.txt"
  else
    warn "Skipping nmap (not installed)"
  fi
else
  warn "Skipping nmap (disabled)"
fi

if [[ "$ENABLE_ZAP" == "true" ]]; then
  if command -v zap-baseline.py >/dev/null 2>&1; then
    info "Running ZAP baseline (native)"
    zap-baseline.py -t "$TARGET_URL" $zap_quick_opts -m "$ZAP_SPIDER_MINS" -T "$ZAP_MAX_DURATION_MINS" -r "$out_dir/zap-report.html" -J "$out_dir/zap-report.json" > "$out_dir/zap.stdout.log" 2>&1 || warn "ZAP baseline returned non-zero status"
    ok "ZAP output: $out_dir/zap-report.html"
  elif [[ "$USE_DOCKER_ZAP" == "true" ]] && command -v docker >/dev/null 2>&1; then
    info "Running ZAP baseline via Docker"
    docker run --rm -v "$out_dir:/zap/wrk" ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t "$TARGET_URL" $zap_quick_opts -m "$ZAP_SPIDER_MINS" -T "$ZAP_MAX_DURATION_MINS" -r zap-report.html -J zap-report.json > "$out_dir/zap.stdout.log" 2>&1 || warn "Docker ZAP baseline returned non-zero status"
    ok "ZAP output: $out_dir/zap-report.html"
  else
    warn "Skipping ZAP (tool unavailable)"
  fi
else
  warn "Skipping ZAP (disabled)"
fi

summary="$out_dir/summary.txt"
{
  echo "target_url=$TARGET_URL"
  echo "target_host=$host"
  echo "timestamp_utc=$timestamp"
  echo "profile=$SCAN_PROFILE"
  echo "authorized=$SECURITY_SCAN_AUTHORIZED"
  echo "authorization_note=$SECURITY_AUTHORIZATION_NOTE"
  echo "output_dir=$out_dir"
} > "$summary"

ok "Scan completed"
ok "Summary: $summary"
