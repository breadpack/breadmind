#!/usr/bin/env bash
set -euo pipefail

# BreadMind Uninstaller for Linux/macOS

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }

ask_yn() {
  local prompt="$1"
  read -rp "$(echo -e "${YELLOW}$prompt [y/N]:${NC} ")" answer
  [[ "$answer" =~ ^[Yy] ]]
}

CONFIG_DIR="${HOME}/.config/breadmind"

echo ""
echo "BreadMind Uninstaller"
echo "====================="
echo ""

# Stop service
case "$(uname -s)" in
  Linux*)
    if systemctl is-active --quiet breadmind 2>/dev/null; then
      info "Stopping BreadMind service..."
      sudo systemctl stop breadmind
      sudo systemctl disable breadmind
      sudo rm -f /etc/systemd/system/breadmind.service
      sudo systemctl daemon-reload
      ok "Service removed."
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

# Remove PostgreSQL container
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q breadmind-postgres; then
  if ask_yn "Remove PostgreSQL container and data?"; then
    docker stop breadmind-postgres 2>/dev/null || true
    docker rm breadmind-postgres 2>/dev/null || true
    docker volume rm breadmind-pgdata 2>/dev/null || true
    ok "PostgreSQL removed."
  else
    info "PostgreSQL container kept."
  fi
fi

# Uninstall package
info "Uninstalling BreadMind..."
pip uninstall -y breadmind 2>/dev/null || python3 -m pip uninstall -y breadmind 2>/dev/null || true
ok "BreadMind uninstalled."

# Config
if [[ -d "$CONFIG_DIR" ]]; then
  if ask_yn "Remove configuration files ($CONFIG_DIR)?"; then
    rm -rf "$CONFIG_DIR"
    ok "Config removed."
  else
    info "Config kept at $CONFIG_DIR"
  fi
fi

echo ""
ok "BreadMind uninstallation complete."
