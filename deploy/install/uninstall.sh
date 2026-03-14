#!/usr/bin/env bash
set -euo pipefail

# BreadMind Uninstaller for Linux/macOS
# Usage: curl -fsSL https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/uninstall.sh | bash
#   or:  ./uninstall.sh [--yes]

CONFIG_DIR="${HOME}/.config/breadmind"
AUTO_YES=false

# Detect if running in a pipe (non-interactive)
IS_INTERACTIVE=true
if [[ ! -t 0 ]]; then
  IS_INTERACTIVE=false
fi

# Parse args
for arg in "$@"; do
  case $arg in
    --yes|-y) AUTO_YES=true ;;
    --help)
      echo "Usage: $0 [--yes]"
      echo ""
      echo "Options:"
      echo "  --yes, -y   Skip confirmation prompts (answer yes to all)"
      echo "  --help      Show this help message"
      exit 0
      ;;
  esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

ask_yn() {
  local prompt="$1"
  local default="${2:-n}"
  if [[ "$AUTO_YES" == true ]]; then
    return 0
  fi
  if [[ "$IS_INTERACTIVE" == false ]]; then
    # Non-interactive without --yes: use default (no for destructive actions)
    [[ "$default" == "y" ]]
    return
  fi
  if [[ "$default" == "y" ]]; then
    read -rp "$(echo -e "${YELLOW}$prompt [Y/n]:${NC} ")" answer
    answer="${answer:-y}"
  else
    read -rp "$(echo -e "${YELLOW}$prompt [y/N]:${NC} ")" answer
    answer="${answer:-n}"
  fi
  [[ "$answer" =~ ^[Yy] ]]
}

echo ""
echo "========================================="
echo "  BreadMind Uninstaller"
echo "========================================="
echo ""

# Confirmation before proceeding
if [[ "$AUTO_YES" == false ]]; then
  if ! ask_yn "This will uninstall BreadMind. Continue?" "y"; then
    info "Uninstall cancelled."
    exit 0
  fi
fi

# -------------------------------------------------------------------
# Stop and remove service
# -------------------------------------------------------------------
case "$(uname -s)" in
  Linux*)
    if systemctl is-active --quiet breadmind 2>/dev/null; then
      info "Stopping BreadMind service..."
      sudo systemctl stop breadmind
      sudo systemctl disable breadmind
      ok "Service stopped."
    fi
    if [[ -f /etc/systemd/system/breadmind.service ]]; then
      info "Removing systemd service file..."
      sudo rm -f /etc/systemd/system/breadmind.service
      sudo systemctl daemon-reload
      ok "Service file removed."
    fi
    ;;
  Darwin*)
    PLIST="$HOME/Library/LaunchAgents/dev.breadpack.breadmind.plist"
    if [[ -f "$PLIST" ]]; then
      info "Stopping BreadMind service..."
      launchctl unload "$PLIST" 2>/dev/null || true
      rm -f "$PLIST"
      ok "Service removed."
    fi
    ;;
esac

# -------------------------------------------------------------------
# Remove PostgreSQL container
# -------------------------------------------------------------------
if command -v docker &>/dev/null; then
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^breadmind-postgres$'; then
    if ask_yn "Remove PostgreSQL container and data? (This will delete all BreadMind database data)"; then
      info "Stopping and removing PostgreSQL container..."
      docker stop breadmind-postgres 2>/dev/null || true
      docker rm breadmind-postgres 2>/dev/null || true
      docker volume rm breadmind-pgdata 2>/dev/null || true
      ok "PostgreSQL container and data removed."
    else
      info "PostgreSQL container kept."
    fi
  fi
fi

# -------------------------------------------------------------------
# Uninstall Python package
# -------------------------------------------------------------------
info "Uninstalling BreadMind Python package..."
for cmd in python3.12 python3 python; do
  if command -v "$cmd" &>/dev/null; then
    "$cmd" -m pip uninstall -y breadmind 2>/dev/null && break
  fi
done || true
ok "BreadMind package uninstalled."

# -------------------------------------------------------------------
# Remove configuration
# -------------------------------------------------------------------
if [[ -d "$CONFIG_DIR" ]]; then
  if ask_yn "Remove configuration files ($CONFIG_DIR)?"; then
    rm -rf "$CONFIG_DIR"
    ok "Configuration removed."
  else
    info "Configuration kept at $CONFIG_DIR"
  fi
fi

echo ""
ok "========================================="
ok "  BreadMind uninstallation complete."
ok "========================================="
echo ""
