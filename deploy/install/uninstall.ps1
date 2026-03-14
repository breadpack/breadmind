#Requires -Version 5.1
# BreadMind Uninstaller for Windows

$ErrorActionPreference = "Stop"
$ConfigDir = Join-Path $env:APPDATA "breadmind"

function Write-Info  { Write-Host "[INFO] $args" -ForegroundColor Blue }
function Write-Ok    { Write-Host "[OK] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN] $args" -ForegroundColor Yellow }

function Ask-YesNo {
    param([string]$Prompt)
    $answer = Read-Host "$Prompt [y/N]"
    return $answer -match '^[Yy]'
}

Write-Host ""
Write-Host "BreadMind Uninstaller" -ForegroundColor Cyan
Write-Host "=====================" -ForegroundColor Cyan
Write-Host ""

# Stop service
Write-Info "Stopping BreadMind service..."
try {
    nssm stop BreadMind 2>$null
    nssm remove BreadMind confirm 2>$null
    Write-Ok "Service removed (nssm)."
} catch {
    try {
        sc.exe stop BreadMind 2>$null
        sc.exe delete BreadMind 2>$null
        Write-Ok "Service removed (sc.exe)."
    } catch {
        Write-Info "No service found."
    }
}

# PostgreSQL container
try {
    $container = docker ps -a --format '{{.Names}}' 2>$null | Where-Object { $_ -eq "breadmind-postgres" }
    if ($container) {
        if (Ask-YesNo "Remove PostgreSQL container and data?") {
            docker stop breadmind-postgres 2>$null
            docker rm breadmind-postgres 2>$null
            docker volume rm breadmind-pgdata 2>$null
            Write-Ok "PostgreSQL removed."
        }
    }
} catch {}

# Uninstall package
Write-Info "Uninstalling BreadMind..."
try { pip uninstall -y breadmind 2>$null } catch {}
try { python -m pip uninstall -y breadmind 2>$null } catch {}
Write-Ok "BreadMind uninstalled."

# Config
if (Test-Path $ConfigDir) {
    if (Ask-YesNo "Remove configuration ($ConfigDir)?") {
        Remove-Item -Recurse -Force $ConfigDir
        Write-Ok "Config removed."
    } else {
        Write-Info "Config kept at $ConfigDir"
    }
}

Write-Host ""
Write-Ok "BreadMind uninstallation complete."
