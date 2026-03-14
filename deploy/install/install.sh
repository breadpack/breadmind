#!/usr/bin/env bash
set -euo pipefail

# BreadMind Installer for Linux/macOS
# Usage: curl -sSL https://get.breadmind.dev | bash
#   or:  ./install.sh [--external-db]

BREADMIND_VERSION="0.1.0"
CONFIG_DIR="${HOME}/.config/breadmind"
EXTERNAL_DB=false

# Parse args
for arg in "$@"; do
  case $arg in
    --external-db) EXTERNAL_DB=true ;;
    --help) echo "Usage: $0 [--external-db]"; exit 0 ;;
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
  local default="${2:-y}"
  if [[ "$default" == "y" ]]; then
    read -rp "$(echo -e "${YELLOW}$prompt [Y/n]:${NC} ")" answer
    answer="${answer:-y}"
  else
    read -rp "$(echo -e "${YELLOW}$prompt [y/N]:${NC} ")" answer
    answer="${answer:-n}"
  fi
  [[ "$answer" =~ ^[Yy] ]]
}

detect_os() {
  case "$(uname -s)" in
    Linux*)  OS="linux" ;;
    Darwin*) OS="macos" ;;
    *)       err "Unsupported OS: $(uname -s)"; exit 1 ;;
  esac
  info "Detected OS: $OS"
}

detect_pkg_manager() {
  if [[ "$OS" == "macos" ]]; then
    PKG_MGR="brew"
  elif command -v apt-get &>/dev/null; then
    PKG_MGR="apt"
  elif command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
  elif command -v pacman &>/dev/null; then
    PKG_MGR="pacman"
  else
    PKG_MGR="unknown"
  fi
}

install_python() {
  info "Installing Python 3.12+..."
  case "$PKG_MGR" in
    brew)
      if ! command -v brew &>/dev/null; then
        info "Installing Homebrew first..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      fi
      brew install python@3.12
      ;;
    apt)
      sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3-pip
      ;;
    dnf)
      sudo dnf install -y python3.12 python3-pip
      ;;
    pacman)
      sudo pacman -Sy --noconfirm python python-pip
      ;;
    *)
      err "Cannot auto-install Python. Please install Python 3.12+ manually."
      exit 1
      ;;
  esac
  ok "Python installed."
}

install_docker() {
  info "Installing Docker..."
  case "$OS" in
    linux)
      curl -fsSL https://get.docker.com | sudo sh
      sudo usermod -aG docker "$USER"
      sudo systemctl enable --now docker
      ;;
    macos)
      if command -v brew &>/dev/null; then
        brew install --cask docker
        info "Please open Docker Desktop to complete setup."
      else
        err "Install Docker Desktop from https://docker.com/products/docker-desktop"
        exit 1
      fi
      ;;
  esac
  ok "Docker installed."
}

check_python() {
  info "Checking Python 3.12+..."
  local py_cmd=""
  for cmd in python3.12 python3 python; do
    if command -v "$cmd" &>/dev/null; then
      local ver
      ver=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
      local major minor
      major=$(echo "$ver" | cut -d. -f1)
      minor=$(echo "$ver" | cut -d. -f2)
      if [[ "$major" -ge 3 && "$minor" -ge 12 ]]; then
        py_cmd="$cmd"
        break
      fi
    fi
  done

  if [[ -z "$py_cmd" ]]; then
    warn "Python 3.12+ not found."
    if ask_yn "Install Python 3.12+?"; then
      install_python
      check_python
      return
    else
      err "Python 3.12+ is required. Please install it and try again."
      exit 1
    fi
  fi
  PYTHON="$py_cmd"
  ok "Python found: $PYTHON ($($PYTHON --version))"
}

check_docker() {
  if [[ "$EXTERNAL_DB" == true ]]; then
    return
  fi
  info "Checking Docker..."
  if ! command -v docker &>/dev/null; then
    warn "Docker not found."
    if ask_yn "Install Docker?"; then
      install_docker
    else
      warn "Switching to --external-db mode."
      EXTERNAL_DB=true
    fi
  else
    ok "Docker found: $(docker --version)"
  fi
}

install_breadmind() {
  info "Installing BreadMind..."
  $PYTHON -m pip install --user breadmind 2>/dev/null || $PYTHON -m pip install breadmind
  ok "BreadMind installed."
}

setup_config() {
  info "Setting up configuration..."
  mkdir -p "$CONFIG_DIR"

  if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
    cat > "$CONFIG_DIR/config.yaml" <<'YAML'
llm:
  default_provider: claude
  default_model: claude-sonnet-4-6
  fallback_chain: [claude, ollama]
  tool_call_max_turns: 10
  tool_call_timeout_seconds: 30

mcp:
  auto_discover: true
  max_restart_attempts: 3
  registries:
    - name: clawhub
      type: clawhub
      enabled: true
    - name: mcp-registry
      type: mcp_registry
      url: https://registry.modelcontextprotocol.io
      enabled: true

database:
  host: ${DB_HOST:-localhost}
  port: ${DB_PORT:-5432}
  name: ${DB_NAME:-breadmind}
  user: ${DB_USER:-breadmind}
  password: ${DB_PASSWORD:-breadmind_dev}
YAML
    ok "Created $CONFIG_DIR/config.yaml"
  else
    ok "Config already exists at $CONFIG_DIR/config.yaml"
  fi

  if [[ ! -f "$CONFIG_DIR/safety.yaml" ]]; then
    cat > "$CONFIG_DIR/safety.yaml" <<'YAML'
blacklist:
  kubernetes:
    - k8s_delete_namespace
    - k8s_drain_node
    - k8s_delete_pv
  proxmox:
    - pve_delete_vm
    - pve_delete_storage
    - pve_format_disk
  openwrt:
    - owrt_factory_reset
    - owrt_firmware_upgrade

require_approval:
  - mcp_install
  - mcp_uninstall
  - pve_create_vm
  - k8s_apply_manifest
  - shell_exec
YAML
    ok "Created $CONFIG_DIR/safety.yaml"
  fi

  # Prompt for API key if not set
  if [[ ! -f "$CONFIG_DIR/.env" ]]; then
    echo ""
    read -rp "$(echo -e "${YELLOW}Enter your Anthropic API key (or press Enter to skip):${NC} ")" api_key
    cat > "$CONFIG_DIR/.env" <<EOF
ANTHROPIC_API_KEY=${api_key}
DB_HOST=localhost
DB_PORT=5432
DB_NAME=breadmind
DB_USER=breadmind
DB_PASSWORD=breadmind_dev
EOF
    ok "Created $CONFIG_DIR/.env"
  fi
}

setup_database() {
  if [[ "$EXTERNAL_DB" == true ]]; then
    info "External database mode. Please configure DB connection in $CONFIG_DIR/config.yaml"
    return
  fi

  info "Starting PostgreSQL container..."
  docker run -d \
    --name breadmind-postgres \
    --restart unless-stopped \
    -e POSTGRES_DB=breadmind \
    -e POSTGRES_USER=breadmind \
    -e POSTGRES_PASSWORD=breadmind_dev \
    -p 5432:5432 \
    -v breadmind-pgdata:/var/lib/postgresql/data \
    pgvector/pgvector:pg17 \
    2>/dev/null || info "PostgreSQL container already exists."
  ok "PostgreSQL running on port 5432."
}

setup_service_linux() {
  info "Setting up systemd service..."
  local breadmind_path
  breadmind_path=$(command -v breadmind 2>/dev/null || echo "$HOME/.local/bin/breadmind")

  sudo tee /etc/systemd/system/breadmind.service > /dev/null <<EOF
[Unit]
Description=BreadMind AI Infrastructure Agent
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=$USER
EnvironmentFile=$CONFIG_DIR/.env
ExecStart=$breadmind_path --config-dir $CONFIG_DIR
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable breadmind
  sudo systemctl start breadmind
  ok "BreadMind service started (systemd)."
}

setup_service_macos() {
  info "Setting up launchd service..."
  local breadmind_path
  breadmind_path=$(command -v breadmind 2>/dev/null || echo "$HOME/.local/bin/breadmind")
  local plist_dir="$HOME/Library/LaunchAgents"
  mkdir -p "$plist_dir"

  cat > "$plist_dir/dev.breadpack.breadmind.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>dev.breadpack.breadmind</string>
    <key>ProgramArguments</key>
    <array>
        <string>$breadmind_path</string>
        <string>--config-dir</string>
        <string>$CONFIG_DIR</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$CONFIG_DIR/breadmind.log</string>
    <key>StandardErrorPath</key>
    <string>$CONFIG_DIR/breadmind.err</string>
</dict>
</plist>
EOF

  launchctl load "$plist_dir/dev.breadpack.breadmind.plist"
  ok "BreadMind service started (launchd)."
}

main() {
  echo ""
  echo "========================================="
  echo "  BreadMind Installer v${BREADMIND_VERSION}"
  echo "  AI Infrastructure Agent"
  echo "========================================="
  echo ""

  detect_os
  detect_pkg_manager
  check_python
  check_docker
  install_breadmind
  setup_config
  setup_database

  case "$OS" in
    linux) setup_service_linux ;;
    macos) setup_service_macos ;;
  esac

  echo ""
  ok "========================================="
  ok "  BreadMind installation complete!"
  ok "========================================="
  echo ""
  info "Config: $CONFIG_DIR"
  info "Logs:   journalctl -u breadmind -f  (Linux)"
  info "        tail -f $CONFIG_DIR/breadmind.log  (macOS)"
  echo ""
}

main "$@"
