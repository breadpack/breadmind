#Requires -Version 5.1
# BreadMind Uninstaller for Windows
# Usage: irm https://raw.githubusercontent.com/breadpack/breadmind/master/deploy/install/uninstall.ps1 | iex
#   or:  .\uninstall.ps1 [-Yes] [-Help]

param(
    [switch]$Yes,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ConfigDir = Join-Path $env:APPDATA "breadmind"

# Detect if running non-interactively (piped from irm)
$script:IsInteractive = [Environment]::UserInteractive -and -not ([Console]::IsInputRedirected)

function Write-Info  { Write-Host "[INFO] $args" -ForegroundColor Blue }
function Write-Ok    { Write-Host "[OK] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[ERROR] $args" -ForegroundColor Red }

function Ask-YesNo {
    param([string]$Prompt, [bool]$Default = $false)
    if ($Yes) { return $true }
    if (-not $script:IsInteractive) { return $Default }
    $suffix = if ($Default) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrEmpty($answer)) { return $Default }
    return $answer -match '^[Yy]'
}

if ($Help) {
    Write-Host "Usage: .\uninstall.ps1 [-Yes] [-Help]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Yes    Skip confirmation prompts (answer yes to all)"
    Write-Host "  -Help   Show this help message"
    exit 0
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  BreadMind Uninstaller" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Confirmation before proceeding
if (-not $Yes) {
    if (-not (Ask-YesNo "This will uninstall BreadMind. Continue?" $true)) {
        Write-Info "Uninstall cancelled."
        exit 0
    }
}

# -------------------------------------------------------------------
# Stop and remove service
# -------------------------------------------------------------------
Write-Info "Stopping BreadMind service..."

# Try NSSM first
$nssmFound = $false
try {
    $nssmPath = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $nssmPath) {
        $localNssm = Join-Path $ConfigDir "bin\nssm.exe"
        if (Test-Path $localNssm) {
            $nssmPath = $localNssm
        }
    }
    if ($nssmPath) {
        $status = & nssm status BreadMind 2>$null
        if ($status -and $status -ne "SERVICE_NOT_FOUND") {
            nssm stop BreadMind 2>$null
            nssm remove BreadMind confirm 2>$null
            Write-Ok "Service removed (NSSM)."
            $nssmFound = $true
        }
    }
} catch {}

# Try sc.exe if NSSM didn't find it
if (-not $nssmFound) {
    try {
        $svc = Get-Service -Name "BreadMind" -ErrorAction SilentlyContinue
        if ($svc) {
            if ($svc.Status -eq "Running") {
                sc.exe stop BreadMind 2>$null
                Start-Sleep -Seconds 2
            }
            sc.exe delete BreadMind 2>$null
            Write-Ok "Service removed (sc.exe)."
        } else {
            Write-Info "No BreadMind service found."
        }
    } catch {
        Write-Info "No BreadMind service found."
    }
}

# -------------------------------------------------------------------
# Remove PostgreSQL container
# -------------------------------------------------------------------
try {
    $dockerAvailable = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerAvailable) {
        $container = docker ps -a --format '{{.Names}}' 2>$null | Where-Object { $_ -eq "breadmind-postgres" }
        if ($container) {
            if (Ask-YesNo "Remove PostgreSQL container and data? (This will delete all BreadMind database data)") {
                Write-Info "Stopping and removing PostgreSQL container..."
                docker stop breadmind-postgres 2>$null
                docker rm breadmind-postgres 2>$null
                docker volume rm breadmind-pgdata 2>$null
                Write-Ok "PostgreSQL container and data removed."
            } else {
                Write-Info "PostgreSQL container kept."
            }
        }
    }
} catch {}

# -------------------------------------------------------------------
# Uninstall Python package
# -------------------------------------------------------------------
Write-Info "Uninstalling BreadMind Python package..."
$uninstalled = $false
foreach ($cmd in @("python", "python3", "py")) {
    try {
        & $cmd -m pip uninstall -y breadmind 2>$null
        if ($LASTEXITCODE -eq 0) {
            $uninstalled = $true
            break
        }
    } catch {}
}
if (-not $uninstalled) {
    Write-Info "BreadMind package was not installed or already removed."
} else {
    Write-Ok "BreadMind package uninstalled."
}

# -------------------------------------------------------------------
# Remove configuration
# -------------------------------------------------------------------
if (Test-Path $ConfigDir) {
    if (Ask-YesNo "Remove configuration files ($ConfigDir)?") {
        Remove-Item -Recurse -Force $ConfigDir
        Write-Ok "Configuration removed."
    } else {
        Write-Info "Configuration kept at $ConfigDir"
    }
}

Write-Host ""
Write-Ok "========================================="
Write-Ok "  BreadMind uninstallation complete."
Write-Ok "========================================="
Write-Host ""
