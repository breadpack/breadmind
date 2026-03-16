"""OS-specific administration skills.

Each skill provides native tool expertise for its platform,
enabling BreadMind to use the optimal commands per environment.
Registered automatically during bootstrap based on detected OS.

Linux skill is further customized by detected package manager/distro
to avoid injecting irrelevant commands into the LLM context.
"""
from __future__ import annotations

import platform
from breadmind.core.skill_store import Skill, SkillStore

# ---------------------------------------------------------------------------
# Linux — distro-specific package management sections
# ---------------------------------------------------------------------------

_LINUX_PKG_DEBIAN = """\
### Package Management (apt — Debian/Ubuntu)
- `apt update && apt install -y <pkg>` — install package
- `apt remove <pkg>`, `apt purge <pkg>` — remove (purge removes config too)
- `apt autoremove` — remove unused dependencies
- `apt search <query>` — search available packages
- `dpkg -l | grep <pkg>` — check if installed
- `apt list --upgradable` — list available upgrades
- `apt upgrade -y` — upgrade all packages
- `add-apt-repository ppa:<repo>` — add PPA (Ubuntu)
- Config: `/etc/apt/sources.list`, `/etc/apt/sources.list.d/`
"""

_LINUX_PKG_RHEL = """\
### Package Management (dnf/yum — RHEL/Fedora/CentOS)
- `dnf install -y <pkg>` — install package
- `dnf remove <pkg>` — remove package
- `dnf search <query>` — search available packages
- `rpm -qa | grep <pkg>` — check if installed
- `dnf check-update` — list available updates
- `dnf upgrade -y` — upgrade all
- `dnf module list` — available module streams
- `dnf config-manager --add-repo <url>` — add repository
- Config: `/etc/yum.repos.d/`
- For older systems, replace `dnf` with `yum`.
"""

_LINUX_PKG_ALPINE = """\
### Package Management (apk — Alpine)
- `apk add <pkg>` — install package
- `apk del <pkg>` — remove package
- `apk search <query>` — search packages
- `apk info` — list installed packages
- `apk update && apk upgrade` — update and upgrade
- Config: `/etc/apk/repositories`
"""

_LINUX_PKG_ARCH = """\
### Package Management (pacman — Arch/Manjaro)
- `pacman -S <pkg>` — install package
- `pacman -R <pkg>`, `pacman -Rns <pkg>` — remove (with deps + config)
- `pacman -Ss <query>` — search packages
- `pacman -Q` — list installed
- `pacman -Syu` — full system upgrade
- `yay -S <pkg>` or `paru -S <pkg>` — AUR packages (if available)
- Config: `/etc/pacman.conf`
"""

_LINUX_PKG_SUSE = """\
### Package Management (zypper — openSUSE/SLES)
- `zypper install <pkg>` — install package
- `zypper remove <pkg>` — remove package
- `zypper search <query>` — search packages
- `zypper update` — update all packages
- `zypper repos` — list repositories
- `zypper addrepo <url> <name>` — add repository
"""

_LINUX_PKG_SNAP_FLATPAK = """\
### Universal Packages
- **Snap**: `snap install <pkg>`, `snap list`, `snap remove <pkg>`
- **Flatpak**: `flatpak install <pkg>`, `flatpak list`, `flatpak uninstall <pkg>`
"""

_LINUX_PKG_GENERIC = """\
### Package Management
- **Debian/Ubuntu**: `apt update && apt install -y <pkg>`, `apt remove <pkg>`
- **RHEL/Fedora**: `dnf install -y <pkg>`, `dnf remove <pkg>`
- **Alpine**: `apk add <pkg>`, `apk del <pkg>`
- **Arch**: `pacman -S <pkg>`, `pacman -R <pkg>`
- Check which package manager is available before using it.
"""

# Common sections shared across all Linux distros
_LINUX_COMMON = """\
### Service Management (systemd)
- `systemctl status <service>` — check status
- `systemctl start|stop|restart|enable|disable <service>`
- `systemctl list-units --type=service --state=running` — list active services
- `journalctl -u <service> -n 50 --no-pager` — recent logs
- `journalctl -u <service> --since "1 hour ago"` — time-filtered logs

### Process Management
- `ps aux --sort=-%mem | head -20` — top memory consumers
- `ps aux --sort=-%cpu | head -20` — top CPU consumers
- `kill -SIGTERM <pid>`, `kill -9 <pid>` — graceful then force
- `pgrep -f <pattern>`, `pkill -f <pattern>` — pattern-based
- `top -bn1 | head -20` — snapshot of system load

### Network
- `ip addr show` — interfaces and IPs
- `ip route show` — routing table
- `ss -tulnp` — listening ports with process info
- `curl -sI <url>` — HTTP health check
- `ping -c 3 <host>` — connectivity test
- `traceroute <host>` or `mtr -n <host>` — path analysis
- `dig <domain>` or `nslookup <domain>` — DNS lookup
- `iptables -L -n` or `nft list ruleset` — firewall rules
- `ufw status` — if UFW is active

### Disk & Storage
- `df -h` — filesystem usage
- `du -sh /path/*` — directory sizes
- `lsblk` — block devices
- `mount | grep -v tmpfs` — mounted filesystems
- `free -h` — memory and swap

### User & Permission
- `whoami`, `id` — current user info
- `useradd -m <user>`, `userdel -r <user>`
- `usermod -aG <group> <user>` — add to group
- `chmod`, `chown` — permission management

### File Operations
- `find /path -name "*.log" -mtime +7 -delete` — cleanup old files
- `tar czf backup.tar.gz /path` — create archive
- `rsync -avz src/ dest/` — sync files

### Monitoring & Diagnostics
- `uptime` — load average
- `vmstat 1 5` — virtual memory stats
- `dmesg -T | tail -30` — kernel messages
- `lsof -i :<port>` — what's using a port

### Container (Docker)
- `docker ps -a` — all containers
- `docker logs <container> --tail 50` — container logs
- `docker stats --no-stream` — resource usage
- `docker exec -it <container> sh` — enter container
- `docker compose up -d`, `docker compose down`

### Kubernetes (if kubectl available)
- `kubectl get pods -A` — all pods
- `kubectl describe pod <name>` — pod details
- `kubectl logs <pod> --tail=50` — pod logs
- `kubectl top nodes`, `kubectl top pods` — resource usage
"""

# Package manager → distro section mapping
_PKG_MANAGER_TO_SECTION: dict[str, str] = {
    "apt": _LINUX_PKG_DEBIAN,
    "apt-get": _LINUX_PKG_DEBIAN,
    "dnf": _LINUX_PKG_RHEL,
    "yum": _LINUX_PKG_RHEL,
    "apk": _LINUX_PKG_ALPINE,
    "pacman": _LINUX_PKG_ARCH,
    "zypper": _LINUX_PKG_SUSE,
    "snap": _LINUX_PKG_SNAP_FLATPAK,
    "flatpak": _LINUX_PKG_SNAP_FLATPAK,
}


def build_linux_prompt(package_managers: list[str] | None = None) -> str:
    """Build a Linux admin prompt tailored to detected package managers.

    If package_managers is provided, only includes the relevant
    package management section(s). Falls back to generic if unknown.
    """
    header = "## Linux System Administration Skill\n\nYou are operating on a Linux system. Use native Linux tools.\n"

    # Select package management sections
    if package_managers:
        seen: set[str] = set()
        pkg_sections: list[str] = []
        for pm in package_managers:
            section = _PKG_MANAGER_TO_SECTION.get(pm.lower())
            if section and section not in seen:
                seen.add(section)
                pkg_sections.append(section)
        if not pkg_sections:
            pkg_sections = [_LINUX_PKG_GENERIC]
    else:
        pkg_sections = [_LINUX_PKG_GENERIC]

    return header + "\n".join(pkg_sections) + "\n" + _LINUX_COMMON


# Default Linux skill (generic — used when no env scan available)
LINUX_SKILL = Skill(
    name="linux_admin",
    description="Linux system administration using native tools",
    prompt_template=build_linux_prompt(),
    steps=[
        "Use detected package manager for installations",
        "Use systemctl for service management",
        "Use native CLI tools for monitoring",
    ],
    trigger_keywords=[
        "linux", "ubuntu", "debian", "centos", "rhel", "fedora", "alpine",
        "arch", "manjaro", "suse",
        "apt", "dnf", "yum", "pacman", "zypper", "systemctl", "journalctl",
        "패키지", "서비스", "프로세스", "디스크", "네트워크", "방화벽",
        "package", "service", "process", "disk", "network", "firewall",
        "docker", "container", "kubernetes", "kubectl",
    ],
    source="builtin",
)

# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

WINDOWS_SKILL = Skill(
    name="windows_admin",
    description="Windows system administration using PowerShell and native tools",
    prompt_template="""\
## Windows System Administration Skill

You are operating on a Windows system. Use PowerShell for all administration tasks.
Always prefix commands with `powershell -Command "..."` when using shell_exec.

### Package Management
- **winget**: `winget install <pkg>`, `winget upgrade --all`, `winget list`
- **choco**: `choco install <pkg> -y`, `choco upgrade all -y`, `choco list --local-only`
- **scoop**: `scoop install <pkg>`, `scoop update *`, `scoop list`
- Check which package manager is available: `Get-Command winget,choco,scoop -ErrorAction SilentlyContinue`

### Service Management
- `Get-Service <name>` — check status
- `Start-Service <name>`, `Stop-Service <name>`, `Restart-Service <name>`
- `Get-Service | Where-Object Status -eq Running` — list running services
- `Set-Service <name> -StartupType Automatic|Manual|Disabled`
- `Get-EventLog -LogName System -Newest 50` — system event logs
- `Get-WinEvent -LogName Application -MaxEvents 50` — application logs

### Process Management
- `Get-Process | Sort-Object WorkingSet64 -Descending | Select -First 20` — top memory
- `Get-Process | Sort-Object CPU -Descending | Select -First 20` — top CPU
- `Stop-Process -Id <pid> -Force` — kill process
- `Stop-Process -Name <name> -Force` — kill by name
- `tasklist /FI "STATUS eq RUNNING"` — classic tasklist

### Network
- `Get-NetIPAddress | Where-Object AddressFamily -eq IPv4` — IP addresses
- `Get-NetRoute` — routing table
- `Get-NetTCPConnection -State Listen` — listening ports
- `Test-NetConnection <host> -Port <port>` — connectivity + port test
- `Resolve-DnsName <domain>` — DNS lookup
- `Get-NetFirewallRule | Where-Object Enabled -eq True` — active firewall rules
- `New-NetFirewallRule -DisplayName <name> -Direction Inbound -Port <port> -Action Allow`
- `ipconfig /all` — full network config

### Disk & Storage
- `Get-PSDrive -PSProvider FileSystem` — drive usage
- `Get-Volume` — all volumes with free space
- `Get-Disk`, `Get-Partition` — physical disks
- `systeminfo | findstr /C:"Total Physical Memory"`

### User & Permission
- `whoami /all` — current user + groups + privileges
- `Get-LocalUser` — list local users
- `New-LocalUser -Name <user> -Password (ConvertTo-SecureString "<pw>" -AsPlainText -Force)`
- `Add-LocalGroupMember -Group Administrators -Member <user>`
- `icacls <path> /grant <user>:F` — file permissions

### File Operations
- `Get-ChildItem -Path C:\\ -Filter *.log -Recurse` — find files
- `Compress-Archive -Path <src> -DestinationPath <dest>.zip` — create archive
- `Expand-Archive -Path <src>.zip -DestinationPath <dest>` — extract
- `robocopy <src> <dest> /MIR` — mirror directories

### Monitoring & Diagnostics
- `Get-ComputerInfo | Select-Object OsName,OsVersion,CsTotalPhysicalMemory` — system info
- `Get-Counter '\\Processor(_Total)\\% Processor Time'` — CPU usage
- `Get-Counter '\\Memory\\Available MBytes'` — available memory
- `systeminfo` — comprehensive system information
- `Get-EventLog -LogName System -EntryType Error -Newest 20` — recent errors

### Scheduled Tasks
- `Get-ScheduledTask | Where-Object State -eq Ready` — active tasks
- `schtasks /query /fo LIST /v` — classic task listing

### WSL (if available)
- `wsl --list --verbose` — WSL distros
- `wsl -d <distro> -- <command>` — run Linux command via WSL
""",
    steps=[
        "Use PowerShell for all commands",
        "Detect available package manager (winget/choco/scoop)",
        "Use Get-Service for service management",
    ],
    trigger_keywords=[
        "windows", "powershell", "winget", "choco", "chocolatey", "scoop",
        "서비스", "프로세스", "디스크", "네트워크", "방화벽", "레지스트리",
        "package", "service", "process", "disk", "network", "firewall",
        "wsl", "iis", "scheduled task", "event log",
    ],
    source="builtin",
)

# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

MACOS_SKILL = Skill(
    name="macos_admin",
    description="macOS system administration using native tools",
    prompt_template="""\
## macOS System Administration Skill

You are operating on macOS. Use native macOS tools and Homebrew for administration.

### Package Management (Homebrew)
- `brew install <pkg>`, `brew upgrade`, `brew list`, `brew uninstall <pkg>`
- **Cask** (GUI apps): `brew install --cask <app>`, `brew list --cask`
- `brew doctor` — diagnose Homebrew issues
- `brew cleanup` — remove old versions
- `mas install <id>` — Mac App Store CLI (if installed)

### Service Management (launchd)
- `brew services list` — Homebrew-managed services
- `brew services start|stop|restart <service>`
- `launchctl list` — all launchd services
- `launchctl load|unload /Library/LaunchDaemons/<plist>`
- `log show --predicate 'process == "<name>"' --last 1h` — unified log

### Process Management
- `ps aux | sort -k 4 -rn | head -20` — top memory consumers
- `ps aux | sort -k 3 -rn | head -20` — top CPU consumers
- `kill -TERM <pid>`, `kill -9 <pid>`
- `pgrep -f <pattern>`, `pkill -f <pattern>`
- `top -l 1 -n 20` — snapshot

### Network
- `ifconfig` — network interfaces
- `networksetup -listallhardwareports` — hardware port listing
- `lsof -iTCP -sTCP:LISTEN -n -P` — listening with process info
- `curl -sI <url>` — HTTP check
- `ping -c 3 <host>`, `traceroute <host>`
- `dscacheutil -flushcache` — flush DNS cache
- `networksetup -setdnsservers Wi-Fi <dns1> <dns2>` — set DNS
- `/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate` — firewall status

### Disk & Storage
- `df -h` — filesystem usage
- `du -sh /path/*` — directory sizes
- `diskutil list` — all disks and partitions
- `tmutil listbackups` — Time Machine backups

### User & Permission
- `whoami`, `id` — current user
- `dscl . -list /Users` — list users
- `chmod`, `chown` — standard POSIX permissions
- `xattr -d com.apple.quarantine <file>` — remove quarantine

### File Operations
- `mdfind "<query>"` — Spotlight search from CLI
- `tar czf backup.tar.gz /path` — archive
- `ditto <src> <dest>` — copy preserving metadata
- `rsync -avz src/ dest/` — sync files
- `open <file>` — open with default app

### Monitoring & Diagnostics
- `system_profiler SPHardwareDataType` — hardware summary
- `sw_vers` — macOS version
- `vm_stat` — virtual memory stats
- `pmset -g batt` — battery status (laptops)
- `log show --last 30m --predicate 'messageType == error'` — recent errors

### macOS-Specific
- `defaults read <domain> <key>` — read preferences
- `defaults write <domain> <key> -<type> <value>` — write preferences
- `osascript -e 'display notification "msg" with title "title"'` — notifications
- `caffeinate -t 3600` — prevent sleep
- `softwareupdate --list` — available OS updates
- `softwareupdate --install --all` — install all updates
""",
    steps=[
        "Use Homebrew for package management",
        "Use launchctl/brew services for service management",
        "Use native macOS CLI tools for monitoring",
    ],
    trigger_keywords=[
        "macos", "mac", "darwin", "brew", "homebrew", "launchctl",
        "패키지", "서비스", "프로세스", "디스크", "네트워크", "방화벽",
        "package", "service", "process", "disk", "network", "firewall",
        "spotlight", "time machine", "gatekeeper",
    ],
    source="builtin",
)

# ---------------------------------------------------------------------------
# Mapping & Registration
# ---------------------------------------------------------------------------

_OS_SKILL_MAP: dict[str, Skill] = {
    "Linux": LINUX_SKILL,
    "Windows": WINDOWS_SKILL,
    "Darwin": MACOS_SKILL,
}


def get_os_skill(os_name: str | None = None) -> Skill | None:
    """Return the appropriate OS skill for the given platform.

    Args:
        os_name: Platform name (Linux, Windows, Darwin).
                 Auto-detected if None.
    """
    if os_name is None:
        os_name = platform.system()
    return _OS_SKILL_MAP.get(os_name)


def get_all_os_skills() -> list[Skill]:
    """Return all OS skills (for worker environments managing multiple OSes)."""
    return list(_OS_SKILL_MAP.values())


async def register_os_skills(
    skill_store: SkillStore,
    os_name: str | None = None,
    package_managers: list[str] | None = None,
):
    """Register OS-appropriate skill(s) in the SkillStore.

    For Linux, uses detected package managers to build a distro-tailored
    prompt instead of the generic one. Skips if already registered.

    Args:
        skill_store: The skill store to register into.
        os_name: Platform name. Auto-detected if None.
        package_managers: Detected package managers from env scan.
                          Used to customize the Linux skill prompt.
    """
    if os_name is None:
        os_name = platform.system()

    skill = _OS_SKILL_MAP.get(os_name)
    if skill is None:
        return

    existing = await skill_store.get_skill(skill.name)
    if existing is not None:
        return

    # For Linux: build distro-tailored prompt if package managers are known
    prompt = skill.prompt_template
    if os_name == "Linux" and package_managers:
        prompt = build_linux_prompt(package_managers)

    await skill_store.add_skill(
        name=skill.name,
        description=skill.description,
        prompt_template=prompt,
        trigger_keywords=skill.trigger_keywords,
        source="builtin",
    )
