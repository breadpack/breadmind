"""Domain-specific administration skills.

Auto-registered based on detected installed software.
Each skill provides OS-aware commands for its domain.
"""
from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass, field
from breadmind.core.skill_store import Skill, SkillStore

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

@dataclass
class DetectedDomain:
    """Result of software detection for a domain."""
    skill_name: str
    detected_tools: list[str] = field(default_factory=list)


def detect_domains() -> list[DetectedDomain]:
    """Detect installed domain software and return matching domains."""
    results: list[DetectedDomain] = []
    os_name = platform.system()

    for domain_name, checks in _DETECTION_MAP.items():
        detected = []
        for tool_name, executables in checks.items():
            for exe in executables:
                if shutil.which(exe):
                    detected.append(tool_name)
                    break
        if detected:
            results.append(DetectedDomain(skill_name=domain_name, detected_tools=detected))

    return results


# tool_name → list of executable names to check
_DETECTION_MAP: dict[str, dict[str, list[str]]] = {
    "webserver_admin": {
        "nginx": ["nginx"],
        "apache": ["apache2", "httpd", "apachectl"],
        "caddy": ["caddy"],
        "traefik": ["traefik"],
    },
    "database_admin": {
        "mysql": ["mysql", "mariadb"],
        "postgresql": ["psql", "pg_dump"],
        "redis": ["redis-cli", "redis-server"],
        "mongodb": ["mongod", "mongosh", "mongo"],
        "sqlite": ["sqlite3"],
    },
    "security_admin": {
        "openssl": ["openssl"],
        "certbot": ["certbot"],
        "ufw": ["ufw"],
        "firewalld": ["firewall-cmd"],
        "fail2ban": ["fail2ban-client"],
    },
    "virtualization_admin": {
        "proxmox": ["qm", "pct"],
        "kvm": ["virsh", "virt-install"],
        "virtualbox": ["VBoxManage", "vboxmanage"],
        "vagrant": ["vagrant"],
    },
    "monitoring_admin": {
        "prometheus": ["prometheus", "promtool"],
        "grafana": ["grafana-server", "grafana-cli"],
        "node_exporter": ["node_exporter"],
        "zabbix": ["zabbix_server", "zabbix_agentd"],
        "netdata": ["netdata"],
    },
    "cicd_admin": {
        "jenkins": ["jenkins"],
        "gitlab_runner": ["gitlab-runner"],
        "github_cli": ["gh"],
        "act": ["act"],
    },
    "storage_admin": {
        "zfs": ["zfs", "zpool"],
        "lvm": ["lvm", "lvs", "vgs", "pvs"],
        "mdadm": ["mdadm"],
        "nfs": ["exportfs", "showmount"],
        "samba": ["smbclient", "smbstatus"],
    },
    "network_infra_admin": {
        "bind": ["named", "rndc"],
        "dnsmasq": ["dnsmasq"],
        "wireguard": ["wg"],
        "openvpn": ["openvpn"],
        "haproxy": ["haproxy"],
    },
}


# ---------------------------------------------------------------------------
# Skill definitions
# ---------------------------------------------------------------------------

WEBSERVER_SKILL = Skill(
    name="webserver_admin",
    description="Web server administration — Nginx, Apache, Caddy, Traefik",
    prompt_template="""\
## Web Server Administration Skill

### Nginx
**Config & Control:**
- `nginx -t` — test configuration syntax
- `nginx -s reload` — reload config without downtime
- `systemctl restart nginx` (Linux) / `brew services restart nginx` (macOS)
- Main config: `/etc/nginx/nginx.conf`
- Sites: `/etc/nginx/sites-available/`, `/etc/nginx/sites-enabled/`
- `ln -s /etc/nginx/sites-available/<site> /etc/nginx/sites-enabled/` — enable site

**Common Tasks:**
- Reverse proxy: `proxy_pass http://localhost:3000;`
- SSL: `ssl_certificate /path/to/cert.pem; ssl_certificate_key /path/to/key.pem;`
- Logs: `tail -f /var/log/nginx/access.log`, `/var/log/nginx/error.log`
- Rate limiting: `limit_req_zone $binary_remote_addr zone=one:10m rate=10r/s;`
- WebSocket proxy: `proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade;`

### Apache (httpd)
**Config & Control:**
- `apachectl configtest` or `httpd -t` — test config
- `systemctl restart apache2` (Debian) / `systemctl restart httpd` (RHEL)
- Main config: `/etc/apache2/apache2.conf` (Debian) / `/etc/httpd/conf/httpd.conf` (RHEL)
- `a2ensite <site>`, `a2dissite <site>` — enable/disable site (Debian)
- `a2enmod <mod>`, `a2dismod <mod>` — enable/disable module

**Common Tasks:**
- Virtual host: `<VirtualHost *:80>` block in sites-available
- SSL: `SSLEngine on; SSLCertificateFile /path/to/cert.pem;`
- Logs: `/var/log/apache2/` or `/var/log/httpd/`
- `.htaccess` for per-directory overrides

### Caddy
- `caddy reload --config /etc/caddy/Caddyfile`
- `caddy validate --config /etc/caddy/Caddyfile`
- Automatic HTTPS by default
- Reverse proxy: `reverse_proxy localhost:3000`

### IIS (Windows)
- `Import-Module WebAdministration` — PowerShell IIS module
- `Get-IISSite` — list sites
- `New-IISSite -Name <name> -BindingInformation "*:80:" -PhysicalPath <path>`
- `Start-IISSite`, `Stop-IISSite`, `Restart-WebAppPool`
- Config: `%SystemRoot%\\System32\\inetsrv\\config\\applicationHost.config`

### Performance & Troubleshooting
- `curl -sI http://localhost` — quick health check
- `ab -n 1000 -c 10 http://localhost/` — Apache Bench load test
- `siege -c 50 -t 30s http://localhost/` — stress test (if installed)
""",
    steps=[
        "Check web server config syntax before reloading",
        "Use appropriate reload command (not restart) for zero-downtime",
        "Check logs when troubleshooting",
    ],
    trigger_keywords=[
        "nginx", "apache", "httpd", "caddy", "traefik", "iis",
        "웹서버", "리버스프록시", "reverse proxy", "ssl", "https",
        "vhost", "virtual host", "사이트", "site",
        "로드밸런서", "load balancer", "upstream",
    ],
    source="builtin",
)

DATABASE_SKILL = Skill(
    name="database_admin",
    description="Database administration — MySQL, PostgreSQL, Redis, MongoDB, SQLite",
    prompt_template="""\
## Database Administration Skill

### MySQL / MariaDB
**Connection & Status:**
- `mysql -u root -p` — connect
- `mysqladmin -u root -p status` — quick status
- `SHOW DATABASES;`, `SHOW TABLES;`, `SHOW PROCESSLIST;`

**Backup & Restore:**
- `mysqldump -u root -p --all-databases > backup.sql` — full backup
- `mysqldump -u root -p <db> > db.sql` — single DB
- `mysql -u root -p <db> < backup.sql` — restore

**Management:**
- `CREATE USER 'user'@'localhost' IDENTIFIED BY 'pass';`
- `GRANT ALL PRIVILEGES ON db.* TO 'user'@'localhost'; FLUSH PRIVILEGES;`
- Config: `/etc/mysql/my.cnf` or `/etc/my.cnf`
- Logs: `/var/log/mysql/error.log`
- `mysqltuner` — performance tuning recommendations (if installed)

### PostgreSQL
**Connection & Status:**
- `psql -U postgres` — connect
- `psql -U postgres -c "SELECT version();"` — check version
- `\\l` — list databases, `\\dt` — list tables, `\\du` — list users

**Backup & Restore:**
- `pg_dump -U postgres <db> > backup.sql` — backup
- `pg_dumpall -U postgres > all.sql` — full cluster backup
- `psql -U postgres <db> < backup.sql` — restore
- `pg_restore -U postgres -d <db> backup.dump` — custom format restore

**Management:**
- `CREATE USER <name> WITH PASSWORD '<pass>';`
- `GRANT ALL PRIVILEGES ON DATABASE <db> TO <user>;`
- Config: `/etc/postgresql/<ver>/main/postgresql.conf`, `pg_hba.conf`
- `pg_isready` — connection check
- `SELECT pg_size_pretty(pg_database_size('<db>'));` — DB size

### Redis
**Connection & Status:**
- `redis-cli` — connect
- `redis-cli ping` — health check (returns PONG)
- `redis-cli info` — full server info
- `redis-cli info memory` — memory usage
- `redis-cli monitor` — real-time command monitoring

**Management:**
- `redis-cli CONFIG GET maxmemory` — check config
- `redis-cli CONFIG SET maxmemory 256mb` — runtime config
- `redis-cli DBSIZE` — key count
- `redis-cli BGSAVE` — background save
- `redis-cli FLUSHDB` — clear current DB (destructive!)
- Config: `/etc/redis/redis.conf`

### MongoDB
**Connection & Status:**
- `mongosh` or `mongo` — connect
- `db.serverStatus()` — server status
- `show dbs`, `show collections`

**Backup & Restore:**
- `mongodump --out /backup/` — backup all
- `mongodump --db <db> --out /backup/` — single DB
- `mongorestore /backup/` — restore

**Management:**
- `db.createUser({user:"admin", pwd:"pass", roles:["root"]})` — create user
- Config: `/etc/mongod.conf`
- `db.stats()` — database statistics

### SQLite
- `sqlite3 <file.db>` — open database
- `.tables` — list tables, `.schema <table>` — show schema
- `.backup <file>` — backup, `.restore <file>` — restore
- `.dump > backup.sql` — SQL dump

### Common Patterns
- Always backup before schema changes
- Check replication status after failover: MySQL `SHOW SLAVE STATUS\\G`, PostgreSQL `SELECT * FROM pg_stat_replication;`
- Monitor slow queries: MySQL `slow_query_log`, PostgreSQL `log_min_duration_statement`
""",
    steps=[
        "Always backup before destructive operations",
        "Use connection check before complex queries",
        "Check logs for errors after configuration changes",
    ],
    trigger_keywords=[
        "mysql", "mariadb", "postgresql", "postgres", "psql",
        "redis", "mongodb", "mongo", "sqlite",
        "데이터베이스", "database", "db", "쿼리", "query",
        "백업", "backup", "복원", "restore", "덤프", "dump",
        "레플리케이션", "replication", "슬로우쿼리", "slow query",
    ],
    source="builtin",
)

SECURITY_SKILL = Skill(
    name="security_admin",
    description="Security administration — SSL/TLS, firewall, audit, hardening",
    prompt_template="""\
## Security Administration Skill

### SSL/TLS Certificate Management
**Let's Encrypt (certbot):**
- `certbot --nginx -d example.com` — auto-configure for Nginx
- `certbot --apache -d example.com` — auto-configure for Apache
- `certbot certonly --standalone -d example.com` — standalone mode
- `certbot renew --dry-run` — test renewal
- `certbot certificates` — list certificates
- Certs stored in: `/etc/letsencrypt/live/<domain>/`
- Auto-renewal: `systemctl enable certbot.timer`

**OpenSSL:**
- `openssl x509 -in cert.pem -text -noout` — inspect certificate
- `openssl s_client -connect host:443` — test TLS connection
- `openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes` — self-signed
- `openssl verify -CAfile ca.pem cert.pem` — verify chain
- `openssl x509 -enddate -noout -in cert.pem` — check expiry

**Windows Certificate:**
- `Get-ChildItem Cert:\\LocalMachine\\My` — list machine certs
- `Import-PfxCertificate -FilePath cert.pfx -CertStoreLocation Cert:\\LocalMachine\\My`

### Firewall Management
**UFW (Ubuntu/Debian):**
- `ufw status verbose` — current rules
- `ufw allow 80/tcp`, `ufw allow 443/tcp` — open ports
- `ufw allow from 10.0.0.0/8 to any port 22` — restrict SSH
- `ufw deny from <ip>` — block IP
- `ufw enable`, `ufw disable`

**firewalld (RHEL/Fedora):**
- `firewall-cmd --state` — check status
- `firewall-cmd --list-all` — current rules
- `firewall-cmd --add-port=80/tcp --permanent` — open port
- `firewall-cmd --add-service=https --permanent`
- `firewall-cmd --reload` — apply changes

**Windows Firewall:**
- `Get-NetFirewallRule | Where-Object Enabled -eq True | Select DisplayName,Direction,Action`
- `New-NetFirewallRule -DisplayName "Allow HTTP" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow`

### Intrusion Prevention
**fail2ban:**
- `fail2ban-client status` — jail summary
- `fail2ban-client status sshd` — SSH jail details
- `fail2ban-client set sshd unbanip <ip>` — unban IP
- Config: `/etc/fail2ban/jail.local`
- Custom filter: `/etc/fail2ban/filter.d/`

### Access Hardening
**SSH Hardening (Linux/macOS):**
- Config: `/etc/ssh/sshd_config`
- `PermitRootLogin no` — disable root login
- `PasswordAuthentication no` — key-only auth
- `AllowUsers <user1> <user2>` — restrict users
- `Port 2222` — change default port
- `systemctl restart sshd` — apply changes

**SELinux (RHEL):**
- `getenforce` — check mode (Enforcing/Permissive/Disabled)
- `setenforce 1` — set enforcing
- `setsebool -P httpd_can_network_connect 1` — allow httpd network
- `audit2allow -a` — generate policy from denials

**AppArmor (Ubuntu):**
- `aa-status` — check profiles
- `aa-enforce /path/to/profile` — enforce profile
- `aa-complain /path/to/profile` — complain mode

### Audit & Monitoring
- `last -20` — recent logins
- `lastb -20` — failed login attempts
- `cat /var/log/auth.log | grep "Failed"` — failed SSH (Debian)
- `journalctl -u sshd --since "1 hour ago"` — SSH logs (systemd)
- `ausearch -m LOGIN --success no -ts recent` — audit failed logins (auditd)
""",
    steps=[
        "Always test config changes before applying",
        "Backup current rules before modifying firewall",
        "Check certificate expiry proactively",
    ],
    trigger_keywords=[
        "ssl", "tls", "https", "인증서", "certificate", "certbot", "letsencrypt",
        "방화벽", "firewall", "ufw", "iptables", "firewalld",
        "보안", "security", "hardening", "경화",
        "fail2ban", "ssh", "selinux", "apparmor",
        "감사", "audit", "로그인", "login", "차단", "block", "ban",
    ],
    source="builtin",
)

VIRTUALIZATION_SKILL = Skill(
    name="virtualization_admin",
    description="Virtualization management — Proxmox, KVM/QEMU, VirtualBox, Vagrant",
    prompt_template="""\
## Virtualization Administration Skill

### Proxmox VE
**VM Management (qm):**
- `qm list` — list all VMs
- `qm status <vmid>` — VM status
- `qm start <vmid>`, `qm stop <vmid>`, `qm reboot <vmid>`
- `qm create <vmid> --name <name> --memory 2048 --cores 2 --net0 virtio,bridge=vmbr0`
- `qm set <vmid> --scsi0 local-lvm:32` — add 32GB disk
- `qm snapshot <vmid> <name>` — create snapshot
- `qm rollback <vmid> <name>` — rollback to snapshot
- `qm clone <vmid> <newid> --name <name>` — clone VM

**Container Management (pct):**
- `pct list` — list containers
- `pct start <ctid>`, `pct stop <ctid>`
- `pct create <ctid> <template> --hostname <name> --memory 512 --rootfs local-lvm:8`
- `pct enter <ctid>` — enter container shell
- `pct exec <ctid> -- <command>` — execute command

**Storage & Backup:**
- `pvesm status` — storage pools
- `vzdump <vmid> --storage <name> --mode snapshot` — backup
- `qmrestore <backup> <vmid>` — restore VM

**Cluster:**
- `pvecm status` — cluster status
- `pvecm nodes` — cluster nodes
- `ha-manager status` — HA status

### KVM/QEMU (virsh)
- `virsh list --all` — list VMs
- `virsh start <name>`, `virsh shutdown <name>`, `virsh destroy <name>`
- `virsh dominfo <name>` — VM details
- `virsh snapshot-create-as <name> <snap>` — snapshot
- `virsh snapshot-revert <name> <snap>` — rollback
- `virt-install --name <name> --ram 2048 --vcpus 2 --disk size=20 --cdrom <iso>` — create VM
- `virsh console <name>` — serial console

### VirtualBox
- `VBoxManage list vms` — list VMs
- `VBoxManage startvm <name> --type headless` — start headless
- `VBoxManage controlvm <name> poweroff|pause|resume`
- `VBoxManage snapshot <name> take <snap>` — snapshot
- `VBoxManage clonevm <name> --name <new>` — clone

### Vagrant
- `vagrant up` — start VM from Vagrantfile
- `vagrant ssh` — SSH into VM
- `vagrant halt` — stop, `vagrant destroy` — remove
- `vagrant status` — check status
- `vagrant snapshot push/pop` — quick snapshots
""",
    steps=[
        "Check VM status before operations",
        "Create snapshot before risky changes",
        "Verify storage space before creating VMs",
    ],
    trigger_keywords=[
        "proxmox", "kvm", "qemu", "virsh", "virtualbox", "vbox", "vagrant",
        "가상머신", "vm", "가상화", "virtualization",
        "스냅샷", "snapshot", "컨테이너", "lxc",
        "하이퍼바이저", "hypervisor", "클론", "clone",
    ],
    source="builtin",
)

MONITORING_SKILL = Skill(
    name="monitoring_admin",
    description="Monitoring stack management — Prometheus, Grafana, exporters, Zabbix",
    prompt_template="""\
## Monitoring Administration Skill

### Prometheus
**Management:**
- Config: `/etc/prometheus/prometheus.yml`
- `promtool check config /etc/prometheus/prometheus.yml` — validate config
- `systemctl reload prometheus` — reload after config change
- Web UI: `http://localhost:9090`

**PromQL Queries:**
- `up` — target health status
- `rate(http_requests_total[5m])` — request rate
- `node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100` — memory %
- `100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)` — CPU %
- `node_filesystem_avail_bytes / node_filesystem_size_bytes * 100` — disk %

**Alert Rules:**
- Rules file: `/etc/prometheus/rules/*.yml`
- `promtool check rules /etc/prometheus/rules/alerts.yml` — validate rules
- `curl http://localhost:9090/api/v1/alerts` — active alerts

### Grafana
- Config: `/etc/grafana/grafana.ini`
- `grafana-cli plugins install <plugin>` — install plugin
- `grafana-cli admin reset-admin-password <pass>` — reset password
- Web UI: `http://localhost:3000` (default admin/admin)
- API: `curl -u admin:pass http://localhost:3000/api/datasources` — list datasources
- Dashboard export: `curl http://localhost:3000/api/dashboards/uid/<uid>`

### Node Exporter (Linux metrics)
- Default port: 9100
- Metrics: `curl http://localhost:9100/metrics`
- `--collector.systemd` — include systemd service metrics
- `--collector.processes` — include process metrics

### Zabbix
- `zabbix_server -R config_cache_reload` — reload config
- `zabbix_get -s <host> -k system.cpu.util` — test item
- Web UI: `http://localhost/zabbix`
- Config: `/etc/zabbix/zabbix_server.conf`

### Netdata
- Web UI: `http://localhost:19999`
- Config: `/etc/netdata/netdata.conf`
- `netdatacli reload-health` — reload alarms

### Common Alerting Patterns
- CPU > 80% for 5m → warning
- Disk > 90% → critical
- Service down for 2m → alert
- Memory < 10% available → warning
""",
    steps=[
        "Validate config before reloading",
        "Check target health after adding new scrape targets",
        "Test alert rules with promtool before deploying",
    ],
    trigger_keywords=[
        "prometheus", "grafana", "zabbix", "netdata", "node_exporter",
        "모니터링", "monitoring", "메트릭", "metrics", "대시보드", "dashboard",
        "알림", "alert", "알람", "alarm", "promql",
        "exporter", "scrape", "타겟", "target",
    ],
    source="builtin",
)

CICD_SKILL = Skill(
    name="cicd_admin",
    description="CI/CD pipeline management — Jenkins, GitLab CI, GitHub Actions",
    prompt_template="""\
## CI/CD Administration Skill

### Jenkins
**Management:**
- Web UI: `http://localhost:8080`
- `systemctl status jenkins` — service status
- Config: `/var/lib/jenkins/` (Linux), `%APPDATA%\\Jenkins` (Windows)
- Initial password: `cat /var/lib/jenkins/secrets/initialAdminPassword`
- CLI: `java -jar jenkins-cli.jar -s http://localhost:8080/ <command>`

**Common Tasks:**
- `jenkins-cli list-jobs` — list all jobs
- `jenkins-cli build <job>` — trigger build
- Plugin management: Manage Jenkins → Plugins
- Backup: archive `/var/lib/jenkins/` directory

### GitLab CI / GitLab Runner
**Runner Management:**
- `gitlab-runner list` — registered runners
- `gitlab-runner status` — runner status
- `gitlab-runner register` — register new runner
- `gitlab-runner verify` — check runner connectivity
- Config: `/etc/gitlab-runner/config.toml`

**Pipeline:**
- `.gitlab-ci.yml` in repo root
- `gitlab-runner exec docker <job>` — test job locally

### GitHub Actions / GitHub CLI
**gh CLI:**
- `gh run list` — list recent workflow runs
- `gh run view <id>` — run details
- `gh run watch <id>` — live watch
- `gh run rerun <id>` — rerun failed
- `gh workflow list` — list workflows
- `gh workflow run <name>` — trigger manually
- `gh pr checks` — check PR status

**act (local testing):**
- `act` — run all workflows locally
- `act -j <job>` — run specific job
- `act --list` — list available jobs

### Common Patterns
- Always pin dependency versions in CI configs
- Use caching: `actions/cache@v4`, GitLab `cache:` directive
- Secrets: use CI/CD variables, never hardcode
""",
    steps=[
        "Check pipeline status before deploying",
        "Review logs for failed jobs",
        "Verify runner connectivity after config changes",
    ],
    trigger_keywords=[
        "jenkins", "gitlab", "github actions", "cicd", "ci/cd",
        "파이프라인", "pipeline", "빌드", "build", "배포", "deploy",
        "러너", "runner", "워크플로우", "workflow",
        "자동화", "automation",
    ],
    source="builtin",
)

STORAGE_SKILL = Skill(
    name="storage_admin",
    description="Storage management — ZFS, LVM, RAID, NFS, SMB/CIFS",
    prompt_template="""\
## Storage Administration Skill

### ZFS
**Pool Management:**
- `zpool status` — pool health
- `zpool list` — pool usage
- `zpool create <pool> mirror <disk1> <disk2>` — mirrored pool
- `zpool add <pool> <disk>` — expand pool
- `zpool scrub <pool>` — integrity check

**Dataset Management:**
- `zfs list` — all datasets
- `zfs create <pool>/<dataset>` — create dataset
- `zfs set compression=lz4 <pool>/<dataset>` — enable compression
- `zfs set quota=100G <pool>/<dataset>` — set quota
- `zfs snapshot <pool>/<dataset>@<name>` — snapshot
- `zfs rollback <pool>/<dataset>@<name>` — rollback
- `zfs send <snap> | zfs recv <dest>` — replicate

### LVM (Logical Volume Manager)
- `pvs` — physical volumes, `vgs` — volume groups, `lvs` — logical volumes
- `pvcreate /dev/sdX` — create PV
- `vgcreate <vg> /dev/sdX` — create VG
- `lvcreate -L 50G -n <lv> <vg>` — create 50GB LV
- `lvextend -L +20G /dev/<vg>/<lv>` — extend by 20GB
- `resize2fs /dev/<vg>/<lv>` — resize ext4 filesystem
- `xfs_growfs /mountpoint` — resize XFS

### Software RAID (mdadm)
- `cat /proc/mdstat` — RAID status
- `mdadm --detail /dev/md0` — array details
- `mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/sd[ab]1` — create RAID1
- `mdadm --manage /dev/md0 --add /dev/sdc1` — add spare
- `mdadm --manage /dev/md0 --remove /dev/sdb1` — remove failed disk

### NFS (Network File System)
**Server (Linux):**
- `cat /etc/exports` — current shares
- `exportfs -ra` — re-export all
- `echo "/shared 10.0.0.0/24(rw,sync,no_subtree_check)" >> /etc/exports`
- `systemctl restart nfs-server`

**Client:**
- `showmount -e <server>` — list server exports
- `mount -t nfs <server>:/shared /mnt/nfs` — mount
- `/etc/fstab`: `<server>:/shared /mnt/nfs nfs defaults 0 0`

### SMB/CIFS (Samba)
**Server (Linux):**
- Config: `/etc/samba/smb.conf`
- `testparm` — validate config
- `smbpasswd -a <user>` — add Samba user
- `systemctl restart smbd`
- `smbstatus` — connected clients

**Client:**
- Linux: `mount -t cifs //<server>/<share> /mnt/smb -o user=<user>`
- Windows: `net use Z: \\\\server\\share /user:<user>`
- macOS: Finder → Go → Connect to Server → `smb://server/share`

### Windows Storage
- `Get-PhysicalDisk` — physical disks
- `Get-StoragePool` — storage pools
- `Get-Volume` — volumes
- `New-Partition -DiskNumber <n> -UseMaximumSize -AssignDriveLetter`
- `Format-Volume -DriveLetter <L> -FileSystem NTFS`
""",
    steps=[
        "Check pool/array health before modifications",
        "Always have backup before RAID rebuild",
        "Verify mount after NFS/SMB configuration",
    ],
    trigger_keywords=[
        "zfs", "lvm", "raid", "mdadm", "nfs", "smb", "cifs", "samba",
        "스토리지", "storage", "볼륨", "volume", "파티션", "partition",
        "마운트", "mount", "공유", "share", "풀", "pool",
        "스냅샷", "snapshot", "레플리케이션", "replication",
    ],
    source="builtin",
)

NETWORK_INFRA_SKILL = Skill(
    name="network_infra_admin",
    description="Network infrastructure — DNS, VPN, load balancer, reverse proxy",
    prompt_template="""\
## Network Infrastructure Administration Skill

### DNS (BIND / CoreDNS / dnsmasq)
**BIND (named):**
- `named-checkconf` — validate config
- `named-checkzone <domain> <zonefile>` — validate zone
- `rndc reload` — reload zones
- `rndc flush` — flush cache
- Config: `/etc/named.conf` or `/etc/bind/named.conf`
- Zones: `/var/named/` or `/etc/bind/zones/`

**dnsmasq:**
- Config: `/etc/dnsmasq.conf` or `/etc/dnsmasq.d/`
- `dnsmasq --test` — validate config
- Add record: `echo "address=/myhost.local/10.0.0.50" >> /etc/dnsmasq.d/local.conf`
- `systemctl restart dnsmasq`

**Windows DNS:**
- `Add-DnsServerPrimaryZone -Name <domain> -ZoneFile <file>`
- `Add-DnsServerResourceRecordA -Name <host> -ZoneName <domain> -IPv4Address <ip>`
- `Get-DnsServerZone` — list zones
- `Resolve-DnsName <domain>` — test resolution

### VPN
**WireGuard:**
- `wg show` — current status
- `wg-quick up wg0`, `wg-quick down wg0` — start/stop
- Config: `/etc/wireguard/wg0.conf`
- Generate keys: `wg genkey | tee private.key | wg pubkey > public.key`
- Add peer: add `[Peer]` section to config

**OpenVPN:**
- `openvpn --config <file.ovpn>` — connect
- `systemctl status openvpn@server` — server status
- Config: `/etc/openvpn/server.conf`
- Easy-RSA for certificate management

### Load Balancer / Reverse Proxy
**HAProxy:**
- Config: `/etc/haproxy/haproxy.cfg`
- `haproxy -c -f /etc/haproxy/haproxy.cfg` — validate config
- `systemctl reload haproxy` — reload
- Stats page: `http://localhost:8404/stats` (if enabled)
- `echo "show stat" | socat stdio /var/run/haproxy.sock` — runtime stats

**Nginx (as LB):**
```
upstream backend {
    server 10.0.0.1:8080 weight=3;
    server 10.0.0.2:8080;
    server 10.0.0.3:8080 backup;
}
```

### Port Forwarding / NAT
**Linux (iptables):**
- `iptables -t nat -A PREROUTING -p tcp --dport 80 -j DNAT --to-destination 10.0.0.5:8080`
- `iptables -t nat -A POSTROUTING -j MASQUERADE`
- `echo 1 > /proc/sys/net/ipv4/ip_forward` — enable forwarding

**Windows:**
- `netsh interface portproxy add v4tov4 listenport=80 connectaddress=10.0.0.5 connectport=8080`
- `netsh interface portproxy show all` — list rules
""",
    steps=[
        "Validate DNS zone files before reloading",
        "Test VPN connectivity after config changes",
        "Check HAProxy config syntax before reload",
    ],
    trigger_keywords=[
        "dns", "bind", "named", "dnsmasq", "coredns",
        "vpn", "wireguard", "openvpn", "터널", "tunnel",
        "로드밸런서", "load balancer", "haproxy",
        "포트포워딩", "port forward", "nat", "프록시", "proxy",
        "도메인", "domain", "zone", "레코드", "record",
    ],
    source="builtin",
)


# ---------------------------------------------------------------------------
# All domain skills
# ---------------------------------------------------------------------------

ALL_DOMAIN_SKILLS: dict[str, Skill] = {
    "webserver_admin": WEBSERVER_SKILL,
    "database_admin": DATABASE_SKILL,
    "security_admin": SECURITY_SKILL,
    "virtualization_admin": VIRTUALIZATION_SKILL,
    "monitoring_admin": MONITORING_SKILL,
    "cicd_admin": CICD_SKILL,
    "storage_admin": STORAGE_SKILL,
    "network_infra_admin": NETWORK_INFRA_SKILL,
}


async def register_domain_skills(skill_store: SkillStore):
    """Detect installed domain software and register matching skills.

    Only registers skills for domains where at least one tool is detected.
    Skips skills that are already registered.
    """
    detected = detect_domains()

    for domain in detected:
        skill = ALL_DOMAIN_SKILLS.get(domain.skill_name)
        if skill is None:
            continue

        existing = await skill_store.get_skill(skill.name)
        if existing is not None:
            continue

        await skill_store.add_skill(
            name=skill.name,
            description=skill.description,
            prompt_template=skill.prompt_template,
            trigger_keywords=skill.trigger_keywords,
            source="builtin",
        )
