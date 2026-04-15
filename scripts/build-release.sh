#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build-release.sh  —  Build the Kendr desktop release package
#
# Usage:
#   ./scripts/build-release.sh              # build for current platform
#   ./scripts/build-release.sh --mac        # macOS DMG (x64 + arm64)
#   ./scripts/build-release.sh --linux      # Linux AppImage + deb (x64)
#   ./scripts/build-release.sh --all        # all platforms (needs macOS host for mac target)
#   ./scripts/build-release.sh --no-sign    # skip macOS code-signing
#
# Output:
#   electron-app/dist/
#     Kendr-<version>-mac-x64.dmg
#     Kendr-<version>-mac-arm64.dmg
#     Kendr Setup <version>.exe
#     Kendr-<version>.AppImage
#     kendr-desktop_<version>_amd64.deb
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ELECTRON_DIR="$ROOT_DIR/electron-app"
RESOURCES_DIR="$ELECTRON_DIR/resources"

BOLD='\033[1m'; TEAL='\033[36m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'
info()  { echo -e "  ${TEAL}▸${RESET} $*"; }
ok()    { echo -e "  ${GREEN}✔${RESET} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${RESET} $*"; }
die()   { echo -e "\n  ${RED}✘ ERROR:${RESET} $*\n" >&2; exit 1; }
banner(){ echo -e "\n${TEAL}${BOLD}  ⚡ Kendr Desktop — Release Builder${RESET}\n"; }

# ── Parse args ───────────────────────────────────────────────────────────────
TARGET=""
NO_SIGN=0
for arg in "$@"; do
  case "$arg" in
    --mac)     TARGET="--mac"   ;;
    --linux)   TARGET="--linux" ;;
    --win)     TARGET="--win"   ;;
    --all)     TARGET="--mac --linux --win" ;;
    --no-sign) NO_SIGN=1 ;;
    *) warn "Unknown argument: $arg" ;;
  esac
done

banner

# ── 1. Check prerequisites ───────────────────────────────────────────────────
info "Checking prerequisites…"

command -v node  >/dev/null 2>&1 || die "Node.js is required. Install from https://nodejs.org"
command -v npm   >/dev/null 2>&1 || die "npm is required. Install from https://nodejs.org"
command -v python3 >/dev/null 2>&1 || die "Python 3.10+ is required to build the bundled backend."

NODE_VER=$(node --version | sed 's/v//')
NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
[[ "$NODE_MAJOR" -ge 18 ]] || die "Node.js 18+ required. Found: v$NODE_VER"
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
  die "Python 3.10+ required. Found: $PY_VER"
fi

ok "Node $(node --version), npm $(npm --version), Python $PY_VER"

# ── 2. Ensure app icons exist ────────────────────────────────────────────────
info "Checking app icons…"
MISSING_ICONS=()

[[ -f "$RESOURCES_DIR/icon.png" ]]  || MISSING_ICONS+=("resources/icon.png  (1024×1024 PNG)")
[[ -f "$RESOURCES_DIR/icon.icns" ]] || MISSING_ICONS+=("resources/icon.icns (macOS icon bundle)")
[[ -f "$RESOURCES_DIR/icon.ico" ]]  || MISSING_ICONS+=("resources/icon.ico  (Windows icon)")

if [[ ${#MISSING_ICONS[@]} -gt 0 ]]; then
  warn "Missing icons (builds will fall back to electron defaults):"
  for i in "${MISSING_ICONS[@]}"; do echo -e "    ${YELLOW}•${RESET} electron-app/$i"; done
  echo ""
  echo -e "  Generate icons from a 1024×1024 PNG using:"
  echo -e "    ${TEAL}./scripts/build-icons.sh path/to/your/logo.png${RESET}"
  echo ""
fi

# ── 3. Install Python release-build dependencies ─────────────────────────────
info "Installing Python packaging dependencies…"
cd "$ROOT_DIR"
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -e ".[bundle]"
ok "Python bundling dependencies installed"

# ── 4. Install Node dependencies ─────────────────────────────────────────────
info "Installing Node dependencies…"
cd "$ELECTRON_DIR"
npm ci --silent
ok "Node dependencies installed"

# Rebuild native modules for the target Electron version
info "Rebuilding native modules (node-pty)…"
npm run rebuild 2>&1 | tail -3 || warn "Rebuild had warnings (may be OK)"

# ── 5. Build Electron (Vite transpile) ───────────────────────────────────────
info "Transpiling with electron-vite…"
npm run build
ok "Electron build complete"

# ── 6. Code signing / notarization env (macOS) ───────────────────────────────
if [[ "$NO_SIGN" -eq 0 ]] && [[ "$(uname)" == "Darwin" ]]; then
  if [[ -z "${CSC_LINK:-}" ]]; then
    warn "CSC_LINK not set — macOS build will be unsigned."
    warn "  Set CSC_LINK=path/to/cert.p12 and CSC_KEY_PASSWORD=... to sign."
    export CSC_IDENTITY_AUTO_DISCOVERY=false
  fi
  if [[ -z "${APPLE_ID:-}" ]]; then
    warn "APPLE_ID not set — notarization will be skipped."
  fi
fi

# ── 7. Package with electron-builder ─────────────────────────────────────────
info "Packaging with electron-builder ${TARGET:-(current platform)}…"
if [[ -n "$TARGET" ]]; then
  # shellcheck disable=SC2086
  npm run package -- $TARGET
else
  npm run package
fi

# ── 8. Report output ─────────────────────────────────────────────────────────
echo ""
ok "${BOLD}Build complete!${RESET}  Artifacts in ${TEAL}electron-app/dist/${RESET}"
echo ""
find "$ELECTRON_DIR/dist" -maxdepth 1 \
  \( -name "*.dmg" -o -name "*.exe" -o -name "*.AppImage" -o -name "*.deb" \) \
  -print | while read -r f; do
    SIZE=$(du -sh "$f" 2>/dev/null | cut -f1)
    echo -e "    ${GREEN}•${RESET} $(basename "$f")  ${TEAL}($SIZE)${RESET}"
  done
echo ""
