#Requires -Version 5.1
# BreadMind Installer for Windows
# Usage: irm https://get.breadmind.dev/windows | iex
#   or:  .\install.ps1 [-ExternalDB]

param(
    [switch]$ExternalDB,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$BreadMindVersion = "0.1.0"
$ConfigDir = Join-Path $env:APPDATA "breadmind"
$NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"

function Write-Info  { Write-Host "[INFO] $args" -ForegroundColor Blue }
function Write-Ok    { Write-Host "[OK] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[ERROR] $args" -ForegroundColor Red }

function Ask-YesNo {
    param([string]$Prompt, [bool]$Default = $true)
    $suffix = if ($Default) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrEmpty($answer)) { return $Default }
    return $answer -match '^[Yy]'
}

function Test-PythonVersion {
    Write-Info "Checking Python 3.12+..."
    foreach ($cmd in @("python", "python3", "py -3.12")) {
        try {
            $ver = & ($cmd.Split()[0]) ($cmd.Split() | Select-Object -Skip 1) -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($ver) {
                $parts = $ver.Split('.')
                if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 12) {
                    $script:PythonCmd = $cmd.Split()[0]
                    Write-Ok "Python found: $($cmd) ($ver)"
                    return $true
                }
            }
        } catch {}
    }
    return $false
}

function Install-Python {
    Write-Info "Installing Python 3.12 via winget..."
    try {
        winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
        Write-Ok "Python installed. You may need to restart your terminal."
    } catch {
        Write-Err "Failed to install Python. Please install Python 3.12+ from https://python.org"
        exit 1
    }
}

function Test-Docker {
    if ($ExternalDB) { return }
    Write-Info "Checking Docker..."
    try {
        $null = docker version 2>$null
        Write-Ok "Docker found."
        return
    } catch {}

    Write-Warn "Docker not found."
    if (Ask-YesNo "Install Docker Desktop?") {
        try {
            winget install Docker.DockerDesktop --accept-source-agreements --accept-package-agreements
            Write-Ok "Docker Desktop installed. Please start Docker Desktop and re-run this installer."
            exit 0
        } catch {
            Write-Err "Failed to install Docker. Please install from https://docker.com"
            exit 1
        }
    } else {
        Write-Warn "Switching to external database mode."
        $script:ExternalDB = $true
    }
}

function Install-BreadMind {
    Write-Info "Installing BreadMind..."
    & $PythonCmd -m pip install breadmind
    Write-Ok "BreadMind installed."
}

function Setup-Config {
    Write-Info "Setting up configuration..."
    if (-not (Test-Path $ConfigDir)) {
        New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    }

    $configPath = Join-Path $ConfigDir "config.yaml"
    if (-not (Test-Path $configPath)) {
        @"
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
  host: localhost
  port: 5432
  name: breadmind
  user: breadmind
  password: breadmind_dev
"@ | Set-Content $configPath -Encoding UTF8
        Write-Ok "Created $configPath"
    }

    $safetyPath = Join-Path $ConfigDir "safety.yaml"
    if (-not (Test-Path $safetyPath)) {
        @"
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
"@ | Set-Content $safetyPath -Encoding UTF8
        Write-Ok "Created $safetyPath"
    }

    # API Key
    $envPath = Join-Path $ConfigDir ".env"
    if (-not (Test-Path $envPath)) {
        $apiKey = Read-Host "Enter your Anthropic API key (or press Enter to skip)"
        @"
ANTHROPIC_API_KEY=$apiKey
DB_HOST=localhost
DB_PORT=5432
DB_NAME=breadmind
DB_USER=breadmind
DB_PASSWORD=breadmind_dev
"@ | Set-Content $envPath -Encoding UTF8
        Write-Ok "Created $envPath"
    }
}

function Setup-Database {
    if ($ExternalDB) {
        Write-Info "External database mode. Configure DB in $ConfigDir\config.yaml"
        return
    }

    Write-Info "Starting PostgreSQL container..."
    try {
        docker run -d `
            --name breadmind-postgres `
            --restart unless-stopped `
            -e POSTGRES_DB=breadmind `
            -e POSTGRES_USER=breadmind `
            -e POSTGRES_PASSWORD=breadmind_dev `
            -p 5432:5432 `
            -v breadmind-pgdata:/var/lib/postgresql/data `
            pgvector/pgvector:pg17 2>$null
        Write-Ok "PostgreSQL running on port 5432."
    } catch {
        Write-Info "PostgreSQL container may already exist."
    }
}

function Install-Nssm {
    if (Get-Command nssm -ErrorAction SilentlyContinue) { return }
    Write-Info "Downloading NSSM..."
    $zipPath = Join-Path $env:TEMP "nssm.zip"
    $extractPath = Join-Path $env:TEMP "nssm"
    Invoke-WebRequest -Uri $NssmUrl -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
    $nssmExe = Get-ChildItem -Path $extractPath -Recurse -Filter "nssm.exe" | Where-Object { $_.DirectoryName -match "win64" } | Select-Object -First 1
    $destDir = Join-Path $ConfigDir "bin"
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    Copy-Item $nssmExe.FullName (Join-Path $destDir "nssm.exe")
    $env:Path += ";$destDir"
    Write-Ok "NSSM installed to $destDir"
}

function Setup-Service {
    Write-Info "Setting up Windows service..."
    Install-Nssm

    $breadmindPath = & $PythonCmd -c "import shutil; print(shutil.which('breadmind') or '')" 2>$null
    if (-not $breadmindPath) {
        $breadmindPath = Join-Path (& $PythonCmd -c "import site; print(site.getusersitepackages().replace('site-packages','Scripts'))") "breadmind.exe"
    }

    try {
        nssm install BreadMind $breadmindPath "--config-dir" $ConfigDir
        nssm set BreadMind AppDirectory $ConfigDir
        nssm set BreadMind Description "BreadMind AI Infrastructure Agent"
        nssm set BreadMind Start SERVICE_AUTO_START
        nssm set BreadMind AppStdout (Join-Path $ConfigDir "breadmind.log")
        nssm set BreadMind AppStderr (Join-Path $ConfigDir "breadmind.err")
        nssm start BreadMind
        Write-Ok "BreadMind service started."
    } catch {
        Write-Warn "NSSM service setup failed. Trying sc.exe fallback..."
        sc.exe create BreadMind binPath= "$breadmindPath --config-dir $ConfigDir" start= auto
        sc.exe start BreadMind
        Write-Ok "BreadMind service started (sc.exe)."
    }
}

# Main
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  BreadMind Installer v$BreadMindVersion" -ForegroundColor Cyan
Write-Host "  AI Infrastructure Agent" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

if ($Help) {
    Write-Host "Usage: .\install.ps1 [-ExternalDB] [-Help]"
    Write-Host "  -ExternalDB  Use external PostgreSQL instead of Docker"
    exit 0
}

if (-not (Test-PythonVersion)) {
    Write-Warn "Python 3.12+ not found."
    if (Ask-YesNo "Install Python 3.12+?") {
        Install-Python
        if (-not (Test-PythonVersion)) {
            Write-Err "Python still not found. Please restart terminal and try again."
            exit 1
        }
    } else {
        Write-Err "Python 3.12+ is required."
        exit 1
    }
}

Test-Docker
Install-BreadMind
Setup-Config
Setup-Database
Setup-Service

Write-Host ""
Write-Ok "========================================="
Write-Ok "  BreadMind installation complete!"
Write-Ok "========================================="
Write-Host ""
Write-Info "Config: $ConfigDir"
Write-Info "Logs:   Get-Content $ConfigDir\breadmind.log -Wait"
Write-Host ""
