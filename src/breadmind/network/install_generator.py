"""Dynamic install script generator for worker deployment.

Generates platform-specific install scripts with embedded
Commander URL and join token. Scripts are served via HTTP endpoint.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def generate_install_script(
    commander_url: str,
    token_secret: str,
    agent_id: str = "",
    os_type: str = "linux",
) -> str:
    """Generate a platform-specific install script.

    Args:
        commander_url: WebSocket URL of the Commander (wss://host:port/ws/agent)
        token_secret: Join token secret for authentication
        agent_id: Optional agent ID (auto-generated if empty)
        os_type: "linux" or "windows"

    Returns:
        Shell script (bash) or PowerShell script content.
    """
    if os_type == "windows":
        return _generate_windows(commander_url, token_secret, agent_id)
    return _generate_linux(commander_url, token_secret, agent_id)


def _generate_linux(commander_url: str, token: str, agent_id: str) -> str:
    agent_id_line = f'AGENT_ID="{agent_id}"' if agent_id else 'AGENT_ID="worker-$(hostname)-$(date +%s)"'

    return f'''#!/bin/bash
set -euo pipefail

# ============================================================
# BreadMind Worker Agent Installer
# Generated dynamically by Commander
# ============================================================

COMMANDER_URL="{commander_url}"
JOIN_TOKEN="{token}"
{agent_id_line}
CONFIG_DIR="${{XDG_CONFIG_HOME:-$HOME/.config}}/breadmind-worker"

echo "=== BreadMind Worker Installer ==="
echo "  Commander: $COMMANDER_URL"
echo "  Agent ID:  $AGENT_ID"
echo ""

# 1. Check Python 3.11+
check_python() {{
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            ver=$("$cmd" -c "import sys; print(f'{{sys.version_info.major}}.{{sys.version_info.minor}}')" 2>/dev/null)
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}}

PYTHON=$(check_python) || {{
    echo "[!] Python 3.11+ not found. Installing..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3 python3-pip
    elif command -v brew &>/dev/null; then
        brew install python3
    elif command -v apk &>/dev/null; then
        apk add python3 py3-pip
    else
        echo "[!] Cannot auto-install Python. Please install Python 3.11+ manually."
        exit 1
    fi
    PYTHON=$(check_python) || {{ echo "[!] Python installation failed."; exit 1; }}
}}

echo "[1/4] Python: $($PYTHON --version)"

# 2. Install BreadMind
echo "[2/4] Installing BreadMind..."
$PYTHON -m pip install --quiet --upgrade breadmind 2>/dev/null || \\
    $PYTHON -m pip install --quiet --upgrade "git+https://github.com/breadmind/breadmind.git"

# 3. Generate config
echo "[3/4] Generating config..."
mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_DIR/config.yaml" << YAML
network:
  mode: worker
  commander_url: "$COMMANDER_URL"
  join_token: "$JOIN_TOKEN"
  agent_id: "$AGENT_ID"
  heartbeat_interval: 30
  offline_threshold: 90
YAML

# 4. Register as system service
echo "[4/4] Setting up service..."
if command -v systemctl &>/dev/null; then
    sudo tee /etc/systemd/system/breadmind-worker.service > /dev/null << SVC
[Unit]
Description=BreadMind Worker Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
ExecStart=$($PYTHON -c "import shutil; print(shutil.which('breadmind') or '$PYTHON -m breadmind')") --mode worker --config-dir $CONFIG_DIR
Restart=always
RestartSec=10
Environment=HOME=$HOME

[Install]
WantedBy=multi-user.target
SVC
    sudo systemctl daemon-reload
    sudo systemctl enable --now breadmind-worker.service
    echo ""
    echo "=== Installation complete ==="
    echo "  Service: breadmind-worker (systemd)"
    echo "  Config:  $CONFIG_DIR/config.yaml"
    echo "  Logs:    journalctl -u breadmind-worker -f"
else
    # Fallback: run in background
    nohup $PYTHON -m breadmind --mode worker --config-dir "$CONFIG_DIR" > "$CONFIG_DIR/worker.log" 2>&1 &
    echo ""
    echo "=== Installation complete ==="
    echo "  Running in background (PID: $!)"
    echo "  Config: $CONFIG_DIR/config.yaml"
    echo "  Logs:   $CONFIG_DIR/worker.log"
fi
'''


def _generate_windows(commander_url: str, token: str, agent_id: str) -> str:
    agent_id_line = f'$AgentId = "{agent_id}"' if agent_id else '$AgentId = "worker-$($env:COMPUTERNAME)-$(Get-Date -Format yyyyMMddHHmmss)"'

    return f'''# ============================================================
# BreadMind Worker Agent Installer (Windows)
# Generated dynamically by Commander
# ============================================================

$ErrorActionPreference = "Stop"

$CommanderUrl = "{commander_url}"
$JoinToken = "{token}"
{agent_id_line}
$ConfigDir = "$env:APPDATA\\breadmind-worker"

Write-Host "=== BreadMind Worker Installer ===" -ForegroundColor Cyan
Write-Host "  Commander: $CommanderUrl"
Write-Host "  Agent ID:  $AgentId"
Write-Host ""

# 1. Check Python 3.11+
$Python = $null
foreach ($cmd in @("python", "python3", "py")) {{
    try {{
        $ver = & $cmd -c "import sys; print(f'{{sys.version_info.major}}.{{sys.version_info.minor}}')" 2>$null
        if ($ver) {{
            $parts = $ver.Split(".")
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 11) {{
                $Python = $cmd
                break
            }}
        }}
    }} catch {{}}
}}

if (-not $Python) {{
    Write-Host "[!] Python 3.11+ not found. Installing via winget..." -ForegroundColor Yellow
    try {{
        winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        $Python = "python"
    }} catch {{
        Write-Host "[!] Auto-install failed. Please install Python 3.11+ manually." -ForegroundColor Red
        exit 1
    }}
}}

Write-Host "[1/4] Python: $(& $Python --version)"

# 2. Install BreadMind
Write-Host "[2/4] Installing BreadMind..."
& $Python -m pip install --quiet --upgrade breadmind 2>$null
if ($LASTEXITCODE -ne 0) {{
    & $Python -m pip install --quiet --upgrade "git+https://github.com/breadmind/breadmind.git"
}}

# 3. Generate config
Write-Host "[3/4] Generating config..."
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
@"
network:
  mode: worker
  commander_url: "$CommanderUrl"
  join_token: "$JoinToken"
  agent_id: "$AgentId"
  heartbeat_interval: 30
  offline_threshold: 90
"@ | Out-File -FilePath "$ConfigDir\\config.yaml" -Encoding utf8

# 4. Start worker
Write-Host "[4/4] Starting worker..."
$BreadmindPath = & $Python -c "import shutil; print(shutil.which('breadmind') or '')" 2>$null
if ($BreadmindPath) {{
    Start-Process -FilePath $BreadmindPath -ArgumentList "--mode worker --config-dir $ConfigDir" -WindowStyle Hidden
}} else {{
    Start-Process -FilePath $Python -ArgumentList "-m breadmind --mode worker --config-dir $ConfigDir" -WindowStyle Hidden
}}

Write-Host ""
Write-Host "=== Installation complete ===" -ForegroundColor Green
Write-Host "  Config: $ConfigDir\\config.yaml"
Write-Host "  To check: Get-Process *breadmind*"
'''
