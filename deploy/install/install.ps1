#Requires -Version 5.1
# BreadMind Installer for Windows
# Usage: irm https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/install.ps1 | iex
#   or:  .\install.ps1 [-ExternalDB] [-Help]

param(
    [switch]$ExternalDB,
    [string]$LocalPath = "",
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$BreadMindVersion = "0.3.0"
$ConfigDir = Join-Path $env:APPDATA "breadmind"
$NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"

$script:DbPort = 5432
$script:DbHost = "localhost"
$script:DbName = "breadmind"
$script:DbUser = "breadmind"
$script:DbPassword = "breadmind_dev"
$script:SkipDockerPg = $false
$script:PythonCmd = $null

# Detect if running non-interactively (piped from irm)
$script:IsInteractive = [Environment]::UserInteractive -and -not ([Console]::IsInputRedirected)

function Write-Info  { Write-Host "[INFO] $args" -ForegroundColor Blue }
function Write-Ok    { Write-Host "[OK] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[ERROR] $args" -ForegroundColor Red }

function Ask-YesNo {
    param([string]$Prompt, [bool]$Default = $true)
    if (-not $script:IsInteractive) {
        return $Default
    }
    $suffix = if ($Default) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrEmpty($answer)) { return $Default }
    return $answer -match '^[Yy]'
}

# -------------------------------------------------------------------
# Port checking
# -------------------------------------------------------------------
function Test-PortAvailable {
    param([int]$Port)
    try {
        $connections = netstat -an 2>$null | Select-String "LISTENING" | Select-String ":$Port\b"
        return ($null -eq $connections -or $connections.Count -eq 0)
    } catch {
        return $true
    }
}

function Test-PortHasPostgres {
    param([int]$Port)
    try {
        $conn = New-Object System.Net.Sockets.TcpClient
        $conn.Connect("localhost", $Port)
        $conn.Close()
        # Port is reachable; check if it's postgres via process
        $listeners = netstat -ano 2>$null | Select-String "LISTENING" | Select-String ":$Port\b"
        if ($listeners) {
            foreach ($line in $listeners) {
                $parts = $line.ToString().Trim() -split '\s+'
                $pid = $parts[-1]
                try {
                    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
                    if ($proc -and $proc.ProcessName -match "postgres") {
                        return $true
                    }
                } catch {}
            }
        }
        return $false
    } catch {
        return $false
    }
}

function Resolve-DbPort {
    if ($ExternalDB) { return }

    # Check if there's already a PostgreSQL on port 5432
    if (-not (Test-PortAvailable -Port 5432)) {
        if (Test-PortHasPostgres -Port 5432) {
            Write-Info "PostgreSQL detected on port 5432."
            if (Ask-YesNo "Use existing PostgreSQL instead of starting a new container?" $true) {
                $script:DbPort = 5432
                $script:SkipDockerPg = $true
                Write-Ok "Will use existing PostgreSQL on port 5432."
                return
            }
        }
        # Port 5432 in use, scan for next free port
        $found = $false
        for ($p = 5433; $p -le 5440; $p++) {
            if (Test-PortAvailable -Port $p) {
                $script:DbPort = $p
                $found = $true
                break
            }
        }
        if (-not $found) {
            Write-Err "No free PostgreSQL port found (5432-5440)."
            Write-Err "Please free a port or use -ExternalDB flag."
            exit 1
        }
        Write-Info "Will use port $($script:DbPort) for PostgreSQL."
    }
}

# -------------------------------------------------------------------
# Python
# -------------------------------------------------------------------
function Test-PythonVersion {
    Write-Info "Checking Python 3.12+..."
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $cmdArgs = @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
            if ($cmd -eq "py") {
                $cmdArgs = @("-3.12") + $cmdArgs
            }
            $ver = & $cmd @cmdArgs 2>$null
            if ($ver) {
                $parts = $ver.Split('.')
                if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 12) {
                    $script:PythonCmd = $cmd
                    if ($cmd -eq "py") {
                        $script:PythonCmd = "py"
                        $script:PythonArgs = @("-3.12")
                    } else {
                        $script:PythonArgs = @()
                    }
                    Write-Ok "Python found: $cmd ($ver)"
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

# -------------------------------------------------------------------
# Docker
# -------------------------------------------------------------------
function Test-Docker {
    if ($ExternalDB) { return }
    if ($script:SkipDockerPg) { return }
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

# -------------------------------------------------------------------
# BreadMind installation
# -------------------------------------------------------------------
function Install-BreadMind {
    Write-Info "Installing BreadMind..."
    $installed = $false

    # If local path provided, install from there
    if ($LocalPath -and (Test-Path $LocalPath)) {
        try {
            & $script:PythonCmd @($script:PythonArgs + @("-m", "pip", "install", $LocalPath))
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "BreadMind installed from local path: $LocalPath"
                $installed = $true
            }
        } catch {}
    }

    # Try PyPI first, fall back to git
    if (-not $installed) {
        try {
            & $script:PythonCmd @($script:PythonArgs + @("-m", "pip", "install", "breadmind")) 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "BreadMind installed from PyPI."
                $installed = $true
            }
        } catch {}
    }

    if (-not $installed) {
        try {
            & $script:PythonCmd @($script:PythonArgs + @("-m", "pip", "install", "git+https://github.com/breadpack/breadmind.git"))
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "BreadMind installed from GitHub."
                $installed = $true
            }
        } catch {}
    }

    if (-not $installed) {
        Write-Err "Failed to install BreadMind. Check your network connection."
        exit 1
    }
}

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
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
  host: $($script:DbHost)
  port: $($script:DbPort)
  name: $($script:DbName)
  user: $($script:DbUser)
  password: $($script:DbPassword)
"@ | Set-Content $configPath -Encoding UTF8
        Write-Ok "Created $configPath"
    } else {
        Write-Ok "Config already exists at $configPath"
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
"@ | Set-Content $safetyPath -Encoding UTF8
        Write-Ok "Created $safetyPath"
    }

    # API Key - create .env in CONFIG_DIR
    $envPath = Join-Path $ConfigDir ".env"
    if (-not (Test-Path $envPath)) {
        $apiKey = ""
        if ($script:IsInteractive) {
            $apiKey = Read-Host "Enter your Anthropic API key (or press Enter to skip)"
        } else {
            Write-Info "Non-interactive mode: skipping API key prompt. Set ANTHROPIC_API_KEY in $envPath later."
        }
        @"
ANTHROPIC_API_KEY=$apiKey
DB_HOST=$($script:DbHost)
DB_PORT=$($script:DbPort)
DB_NAME=$($script:DbName)
DB_USER=$($script:DbUser)
DB_PASSWORD=$($script:DbPassword)
"@ | Set-Content $envPath -Encoding UTF8
        Write-Ok "Created $envPath"
    }
}

# -------------------------------------------------------------------
# Database
# -------------------------------------------------------------------
function Setup-Database {
    if ($ExternalDB) {
        Write-Info "External database mode. Configure DB in $ConfigDir\config.yaml"
        return
    }

    if ($script:SkipDockerPg) {
        Write-Ok "Using existing PostgreSQL on port $($script:DbPort) (no Docker container needed)."
        return
    }

    Write-Info "Starting PostgreSQL container on port $($script:DbPort)..."
    try {
        docker run -d `
            --name breadmind-postgres `
            --restart unless-stopped `
            -e POSTGRES_DB=$($script:DbName) `
            -e POSTGRES_USER=$($script:DbUser) `
            -e POSTGRES_PASSWORD=$($script:DbPassword) `
            -p "$($script:DbPort):5432" `
            -v breadmind-pgdata:/var/lib/postgresql/data `
            pgvector/pgvector:pg17 2>$null
        Write-Ok "PostgreSQL running on port $($script:DbPort)."
    } catch {
        # Container might already exist - try starting it
        try {
            docker start breadmind-postgres 2>$null
            Write-Ok "Existing PostgreSQL container started."
        } catch {
            Write-Info "PostgreSQL container may already be running."
        }
    }
}

# -------------------------------------------------------------------
# Service setup
# -------------------------------------------------------------------
function Install-Nssm {
    if (Get-Command nssm -ErrorAction SilentlyContinue) { return $true }
    # Check if already in config bin
    $existingNssm = Join-Path $ConfigDir "bin\nssm.exe"
    if (Test-Path $existingNssm) {
        $env:Path += ";$(Join-Path $ConfigDir 'bin')"
        return $true
    }
    Write-Info "Downloading NSSM..."
    try {
        $zipPath = Join-Path $env:TEMP "nssm.zip"
        $extractPath = Join-Path $env:TEMP "nssm"
        Invoke-WebRequest -Uri $NssmUrl -OutFile $zipPath -TimeoutSec 15
        Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
        $nssmExe = Get-ChildItem -Path $extractPath -Recurse -Filter "nssm.exe" | Where-Object { $_.DirectoryName -match "win64" } | Select-Object -First 1
        $destDir = Join-Path $ConfigDir "bin"
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        Copy-Item $nssmExe.FullName (Join-Path $destDir "nssm.exe")
        $env:Path += ";$destDir"
        Write-Ok "NSSM installed to $destDir"
        return $true
    } catch {
        Write-Warn "NSSM download failed (server may be unavailable)."
        return $false
    }
}

function Setup-Service {
    Write-Info "Setting up Windows service..."

    # Get Python executable path
    $pythonPath = & $script:PythonCmd @($script:PythonArgs + @("-c", "import sys; print(sys.executable)")) 2>$null
    if (-not $pythonPath) {
        Write-Err "Could not determine Python executable path."
        exit 1
    }

    $logFile = Join-Path $ConfigDir "breadmind.log"
    $errFile = Join-Path $ConfigDir "breadmind.err"
    $started = $false

    # Strategy 1: NSSM service
    if (Install-Nssm) {
        try {
            nssm install BreadMind $pythonPath "-m" "breadmind" "--web" "--config-dir" $ConfigDir
            nssm set BreadMind AppDirectory $ConfigDir
            nssm set BreadMind Description "BreadMind AI Infrastructure Agent"
            nssm set BreadMind Start SERVICE_AUTO_START
            nssm set BreadMind AppEnvironmentExtra "PYTHONUNBUFFERED=1"
            nssm set BreadMind AppStdout $logFile
            nssm set BreadMind AppStderr $errFile
            nssm start BreadMind
            Write-Ok "BreadMind service started (NSSM)."
            $started = $true
        } catch {
            Write-Warn "NSSM service setup failed: $_"
        }
    }

    # Strategy 2: Start as background process
    if (-not $started) {
        Write-Info "Starting BreadMind as background process..."
        $env:PYTHONUNBUFFERED = "1"
        $proc = Start-Process -FilePath $pythonPath `
            -ArgumentList "-m", "breadmind", "--web", "--config-dir", $ConfigDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $logFile `
            -RedirectStandardError $errFile `
            -PassThru
        if ($proc) {
            Write-Ok "BreadMind started (PID: $($proc.Id))"
            Write-Info "Note: Process will stop when you log out. For persistent service, install NSSM manually."
            $started = $true
        }
    }

    if (-not $started) {
        Write-Err "Failed to start BreadMind. Run manually:"
        Write-Err "  $pythonPath -m breadmind --web --config-dir `"$ConfigDir`""
    }
}

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  BreadMind Installer v$BreadMindVersion" -ForegroundColor Cyan
Write-Host "  AI Infrastructure Agent" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

if ($Help) {
    Write-Host "Usage: .\install.ps1 [-ExternalDB] [-Help]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -ExternalDB  Use an existing PostgreSQL instead of starting a Docker container"
    Write-Host "  -Help        Show this help message"
    Write-Host ""
    Write-Host "One-liner install:"
    Write-Host "  irm https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/install.ps1 | iex"
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

Resolve-DbPort
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
Write-Info "DB Port: $($script:DbPort)"
Write-Info "Logs:   Get-Content $ConfigDir\breadmind.log -Wait"
Write-Host ""
