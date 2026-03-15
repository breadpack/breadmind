#!/usr/bin/env bash
set -euo pipefail

# BreadMind Worker Installer
# Lightweight agent that connects to a Commander instance.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/install-worker.sh | bash -s -- --commander wss://your-commander:8081/ws/agent/self
#   or: ./install-worker.sh --commander wss://commander:8081/ws/agent/self [--agent-id myworker] [--help]

BREADMIND_VERSION="0.1.0"
CONFIG_DIR="${HOME}/.config/breadmind-worker"
COMMANDER_URL=""
AGENT_ID=""

# Detect if running in a pipe (non-interactive)
IS_INTERACTIVE=true
if [[ ! -t 0 ]]; then
  IS_INTERACTIVE=false
fi

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --commander)  COMMANDER_URL="$2"; shift 2 ;;
    --agent-id)   AGENT_ID="$2"; shift 2 ;;
    --config-dir) CONFIG_DIR="$2"; shift 2 ;;
    --help)
      echo "Usage: $0 --commander <wss://commander:8081/ws/agent/self> [options]"
      echo ""
      echo "Required:"
      echo "  --commander URL    Commander WebSocket URL"
      echo ""
      echo "Options:"
      echo "  --agent-id NAME    Worker agent ID (default: hostname)"
      echo "  --config-dir DIR   Config directory (default: ~/.config/breadmind-worker)"
      echo "  --help             Show this help message"
      echo ""
      echo "One-liner install:"
      echo "  curl -fsSL https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/install-worker.sh | bash -s -- --commander wss://your-commander:8081/ws/agent/self"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
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

# -------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------
validate_args() {
  if [[ -z "$COMMANDER_URL" ]]; then
    if [[ "$IS_INTERACTIVE" == true ]]; then
      read -rp "$(echo -e "${YELLOW}Commander WebSocket URL:${NC} ")" COMMANDER_URL
    fi
    if [[ -z "$COMMANDER_URL" ]]; then
      err "--commander URL is required."
      err "Example: $0 --commander wss://192.168.1.100:8081/ws/agent/self"
      exit 1
    fi
  fi

  if [[ -z "$AGENT_ID" ]]; then
    AGENT_ID="$(hostname -s 2>/dev/null || hostname)"
  fi
}

# -------------------------------------------------------------------
# OS detection
# -------------------------------------------------------------------
detect_os() {
  case "$(uname -s)" in
    Linux*)  OS="linux" ;;
    Darwin*) OS="macos" ;;
    *)       err "Unsupported OS: $(uname -s)"; exit 1 ;;
  esac

  # Detect if OpenWrt
  IS_OPENWRT=false
  if [[ -f /etc/openwrt_release ]]; then
    IS_OPENWRT=true
  fi

  info "Detected OS: $OS$([ "$IS_OPENWRT" == true ] && echo ' (OpenWrt)')"
}

detect_pkg_manager() {
  if [[ "$IS_OPENWRT" == true ]]; then
    PKG_MGR="opkg"
  elif [[ "$OS" == "macos" ]]; then
    PKG_MGR="brew"
  elif command -v apt-get &>/dev/null; then
    PKG_MGR="apt"
  elif command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
  elif command -v pacman &>/dev/null; then
    PKG_MGR="pacman"
  elif command -v apk &>/dev/null; then
    PKG_MGR="apk"
  else
    PKG_MGR="unknown"
  fi
}

# -------------------------------------------------------------------
# Python (lightweight check — worker needs minimal deps)
# -------------------------------------------------------------------
install_python() {
  info "Installing Python 3.11+..."
  case "$PKG_MGR" in
    brew)   brew install python@3.12 ;;
    apt)    sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip ;;
    dnf)    sudo dnf install -y python3 python3-pip ;;
    pacman) sudo pacman -Sy --noconfirm python python-pip ;;
    apk)    sudo apk add python3 py3-pip ;;
    opkg)   opkg update && opkg install python3 python3-pip ;;
    *)      err "Cannot auto-install Python. Please install Python 3.11+ manually."; exit 1 ;;
  esac
  ok "Python installed."
}

check_python() {
  info "Checking Python 3.11+..."
  local py_cmd=""
  for cmd in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
      local ver
      ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null) || continue
      local major minor
      major=$(echo "$ver" | cut -d. -f1)
      minor=$(echo "$ver" | cut -d. -f2)
      if [[ "$major" -ge 3 && "$minor" -ge 11 ]]; then
        py_cmd="$cmd"
        break
      fi
    fi
  done

  if [[ -z "$py_cmd" ]]; then
    warn "Python 3.11+ not found."
    install_python
    check_python
    return
  fi
  PYTHON="$py_cmd"
  ok "Python found: $PYTHON ($($PYTHON --version))"
}

# -------------------------------------------------------------------
# BreadMind Worker installation
# -------------------------------------------------------------------
install_worker() {
  info "Installing BreadMind (worker dependencies only)..."
  if $PYTHON -m pip install --user breadmind 2>/dev/null; then
    ok "BreadMind installed from PyPI."
  elif $PYTHON -m pip install --user "git+https://github.com/breadpack/breadmind.git" 2>/dev/null; then
    ok "BreadMind installed from GitHub."
  else
    if $PYTHON -m pip install breadmind 2>/dev/null; then
      ok "BreadMind installed from PyPI."
    elif $PYTHON -m pip install "git+https://github.com/breadpack/breadmind.git"; then
      ok "BreadMind installed from GitHub."
    else
      err "Failed to install BreadMind. Check your network connection."
      exit 1
    fi
  fi
}

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
setup_config() {
  info "Setting up worker configuration..."
  mkdir -p "$CONFIG_DIR"

  cat > "$CONFIG_DIR/config.yaml" <<YAML
# BreadMind Worker Configuration
# Auto-generated by install-worker.sh

network:
  mode: worker
  commander_url: "${COMMANDER_URL}"
  heartbeat_interval: 30
  offline_threshold: 90
  offline_queue_max_rows: 10000
  offline_queue_max_mb: 100

llm:
  # Worker does not call LLM directly — proxied through Commander
  default_provider: none

logging:
  level: INFO
YAML
  ok "Created $CONFIG_DIR/config.yaml"
}

# -------------------------------------------------------------------
# Service setup
# -------------------------------------------------------------------
setup_service_linux() {
  if [[ "$IS_OPENWRT" == true ]]; then
    setup_service_openwrt
    return
  fi

  info "Setting up systemd service..."
  sudo tee /etc/systemd/system/breadmind-worker.service > /dev/null <<EOF
[Unit]
Description=BreadMind Worker Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
ExecStart=$PYTHON -m breadmind --mode worker --commander-url ${COMMANDER_URL} --config-dir ${CONFIG_DIR}
Restart=always
RestartSec=5
Environment=BREADMIND_AGENT_ID=${AGENT_ID}

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable breadmind-worker
  sudo systemctl start breadmind-worker
  ok "Worker service started (systemd)."
}

setup_service_openwrt() {
  info "Setting up init.d service for OpenWrt..."
  cat > /etc/init.d/breadmind-worker <<EOF
#!/bin/sh /etc/rc.common

START=99
STOP=10
USE_PROCD=1

start_service() {
    procd_open_instance
    procd_set_param command $PYTHON -m breadmind --mode worker --commander-url ${COMMANDER_URL} --config-dir ${CONFIG_DIR}
    procd_set_param env BREADMIND_AGENT_ID=${AGENT_ID}
    procd_set_param respawn
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
EOF
  chmod +x /etc/init.d/breadmind-worker
  /etc/init.d/breadmind-worker enable
  /etc/init.d/breadmind-worker start
  ok "Worker service started (procd)."
}

setup_service_macos() {
  info "Setting up launchd service..."
  local python_path
  python_path=$(command -v "$PYTHON")
  local plist_dir="$HOME/Library/LaunchAgents"
  mkdir -p "$plist_dir"

  cat > "$plist_dir/dev.breadpack.breadmind-worker.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>dev.breadpack.breadmind-worker</string>
    <key>ProgramArguments</key>
    <array>
        <string>$python_path</string>
        <string>-m</string>
        <string>breadmind</string>
        <string>--mode</string>
        <string>worker</string>
        <string>--commander-url</string>
        <string>${COMMANDER_URL}</string>
        <string>--config-dir</string>
        <string>${CONFIG_DIR}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$HOME/.local/bin</string>
        <key>BREADMIND_AGENT_ID</key>
        <string>${AGENT_ID}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${CONFIG_DIR}/worker.log</string>
    <key>StandardErrorPath</key>
    <string>${CONFIG_DIR}/worker.err</string>
</dict>
</plist>
EOF

  launchctl unload "$plist_dir/dev.breadpack.breadmind-worker.plist" 2>/dev/null || true
  launchctl load "$plist_dir/dev.breadpack.breadmind-worker.plist"
  ok "Worker service started (launchd)."
}

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
main() {
  echo ""
  echo "========================================="
  echo "  BreadMind Worker Installer v${BREADMIND_VERSION}"
  echo "  Lightweight Agent for Remote Nodes"
  echo "========================================="
  echo ""

  validate_args
  detect_os
  detect_pkg_manager
  check_python
  install_worker
  setup_config

  case "$OS" in
    linux) setup_service_linux ;;
    macos) setup_service_macos ;;
  esac

  echo ""
  ok "========================================="
  ok "  BreadMind Worker installation complete!"
  ok "========================================="
  echo ""
  info "Agent ID:   $AGENT_ID"
  info "Commander:  $COMMANDER_URL"
  info "Config:     $CONFIG_DIR"
  if [[ "$IS_OPENWRT" == true ]]; then
    info "Logs:       logread -e breadmind"
    info "Control:    /etc/init.d/breadmind-worker {start|stop|restart}"
  elif [[ "$OS" == "linux" ]]; then
    info "Logs:       journalctl -u breadmind-worker -f"
    info "Control:    systemctl {start|stop|restart} breadmind-worker"
  else
    info "Logs:       tail -f $CONFIG_DIR/worker.log"
  fi
  echo ""
}

main "$@"
