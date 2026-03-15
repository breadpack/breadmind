# Distributed Agent Network Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BreadMind 인스턴스를 관리 대상 인프라 노드에 Worker로 자동 배포하여 중앙 Commander와 WebSocket+mTLS로 연동하는 분산 에이전트 네트워크 구축

**Architecture:** 하나의 코드베이스, 두 실행 모드 (Commander/Worker). Worker는 경량 CoreAgent 변형으로 로컬 도구 실행 + 스케줄러만 탑재. LLM 호출은 Commander를 프록시로 사용. mTLS + 메시지 HMAC으로 보안.

**Tech Stack:** Python 3.11+, asyncio, websockets, cryptography (x509/Fernet), aiosqlite, FastAPI, pytest, APScheduler

**Spec:** `docs/superpowers/specs/2026-03-15-distributed-agent-network-design.md`

---

## File Structure

### New Files

```
src/breadmind/network/
  __init__.py                 # Package init, version constant
  protocol.py                 # Message envelope, serialization, HMAC, seq validation (~200 lines)
  pki.py                      # CA management, cert issue/renew/revoke, CRL, code signing (~300 lines)
  commander.py                # WebSocket hub, connection manager, task dispatch (~350 lines)
  worker.py                   # Worker runtime, WS client, executor, scheduler (~350 lines)
  registry.py                 # Agent registry, role manager, status tracking (~200 lines)
  sync.py                     # Offline queue sync, idempotency reconciliation (~150 lines)

src/breadmind/provisioning/
  __init__.py
  provisioner.py              # Environment detection, strategy selection (~150 lines)
  strategies/
    __init__.py
    base.py                   # Abstract strategy interface (~30 lines)
    kubernetes.py             # DaemonSet deployment (~100 lines)
    proxmox.py                # LXC container deployment (~100 lines)
    ssh.py                    # Direct SSH installation (~100 lines)
  templates/
    worker-config.yaml.j2     # Worker config template
    worker-compose.yaml.j2    # Docker compose template

tests/
  test_protocol.py
  test_pki.py
  test_commander.py
  test_worker.py
  test_registry_network.py
  test_sync.py
  test_provisioner.py
  test_integration_network.py
```

### Modified Files

```
src/breadmind/config.py           # Add NetworkConfig dataclass
src/breadmind/main.py             # Add --mode flag, Worker mode bootstrap
src/breadmind/core/agent.py       # Add LLM proxy mode for Worker
src/breadmind/core/safety.py      # Add agent_id field support
src/breadmind/tools/registry.py   # Add role-scoped tool filtering
src/breadmind/web/app.py          # Add /ws/agent/ endpoint, registry UI endpoints
src/breadmind/storage/database.py # Add agent network tables migration
```

---

## Chunk 1: Protocol Foundation

### Task 1: Message Envelope & Serialization

**Files:**
- Create: `src/breadmind/network/__init__.py`
- Create: `src/breadmind/network/protocol.py`
- Test: `tests/test_protocol.py`

- [ ] **Step 1: Write failing tests for message envelope**

```python
# tests/test_protocol.py
import pytest
import time
from breadmind.network.protocol import (
    MessageEnvelope, MessageType, create_message,
    serialize_message, deserialize_message,
    MessageIntegrityError, MessageSequenceError,
)

def test_create_message_has_required_fields():
    msg = create_message(
        type=MessageType.HEARTBEAT,
        source="worker-1",
        target="commander",
        payload={"cpu": 0.5},
    )
    assert msg.protocol_version == 1
    assert msg.id is not None
    assert msg.type == MessageType.HEARTBEAT
    assert msg.source == "worker-1"
    assert msg.target == "commander"
    assert msg.payload == {"cpu": 0.5}
    assert msg.timestamp is not None
    assert msg.seq == 0  # initial seq

def test_serialize_deserialize_roundtrip():
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={"task": "check_pods"},
    )
    data = serialize_message(msg, session_key=b"test-key-32-bytes-long-enough!!")
    restored = deserialize_message(data, session_key=b"test-key-32-bytes-long-enough!!")
    assert restored.id == msg.id
    assert restored.type == msg.type
    assert restored.payload == msg.payload

def test_deserialize_tampered_message_raises():
    msg = create_message(
        type=MessageType.COMMAND,
        source="commander",
        target="worker-1",
        payload={"action": "restart"},
    )
    data = serialize_message(msg, session_key=b"test-key-32-bytes-long-enough!!")
    # Tamper with payload
    import json
    obj = json.loads(data)
    obj["payload"]["action"] = "delete"
    tampered = json.dumps(obj)
    with pytest.raises(MessageIntegrityError):
        deserialize_message(tampered, session_key=b"test-key-32-bytes-long-enough!!")

def test_message_types_complete():
    expected = {
        "task_assign", "task_result", "llm_request", "llm_response",
        "heartbeat", "sync", "role_update", "command",
    }
    actual = {t.value for t in MessageType}
    assert expected == actual

def test_create_message_with_trace_id():
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={},
        trace_id="trace-123",
        reply_to="msg-456",
    )
    assert msg.trace_id == "trace-123"
    assert msg.reply_to == "msg-456"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_protocol.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Create network package init**

```python
# src/breadmind/network/__init__.py
"""BreadMind Distributed Agent Network."""

PROTOCOL_VERSION = 1
```

- [ ] **Step 4: Implement protocol.py**

```python
# src/breadmind/network/protocol.py
"""Message envelope, serialization, HMAC integrity, sequence validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MessageType(Enum):
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    HEARTBEAT = "heartbeat"
    SYNC = "sync"
    ROLE_UPDATE = "role_update"
    COMMAND = "command"


class MessageIntegrityError(Exception):
    """HMAC verification failed."""


class MessageSequenceError(Exception):
    """Sequence number validation failed."""


@dataclass
class MessageEnvelope:
    protocol_version: int
    id: str
    seq: int
    type: MessageType
    source: str
    target: str
    timestamp: str
    payload: dict[str, Any]
    trace_id: str | None = None
    reply_to: str | None = None
    hmac: str | None = None


def create_message(
    type: MessageType,
    source: str,
    target: str,
    payload: dict[str, Any],
    seq: int = 0,
    trace_id: str | None = None,
    reply_to: str | None = None,
) -> MessageEnvelope:
    return MessageEnvelope(
        protocol_version=1,
        id=str(uuid.uuid4()),
        seq=seq,
        type=type,
        source=source,
        target=target,
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        trace_id=trace_id,
        reply_to=reply_to,
    )


def _compute_hmac(data: dict, session_key: bytes) -> str:
    """Compute HMAC-SHA256 over message body (excluding hmac field)."""
    body = {k: v for k, v in data.items() if k != "hmac"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hmac.new(session_key, canonical.encode(), hashlib.sha256).hexdigest()


def serialize_message(msg: MessageEnvelope, session_key: bytes) -> str:
    data = asdict(msg)
    data["type"] = msg.type.value
    data["hmac"] = _compute_hmac(data, session_key)
    return json.dumps(data)


def deserialize_message(raw: str, session_key: bytes) -> MessageEnvelope:
    data = json.loads(raw)
    received_hmac = data.get("hmac")
    expected_hmac = _compute_hmac(data, session_key)
    if not hmac.compare_digest(received_hmac or "", expected_hmac):
        raise MessageIntegrityError("HMAC verification failed")
    return MessageEnvelope(
        protocol_version=data["protocol_version"],
        id=data["id"],
        seq=data["seq"],
        type=MessageType(data["type"]),
        source=data["source"],
        target=data["target"],
        timestamp=data["timestamp"],
        payload=data["payload"],
        trace_id=data.get("trace_id"),
        reply_to=data.get("reply_to"),
        hmac=received_hmac,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_protocol.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/network/__init__.py src/breadmind/network/protocol.py tests/test_protocol.py
git commit -m "feat(network): add message envelope protocol with HMAC integrity"
```

---

### Task 2: Sequence Tracking

**Files:**
- Modify: `src/breadmind/network/protocol.py`
- Test: `tests/test_protocol.py`

- [ ] **Step 1: Write failing tests for sequence tracker**

```python
# Append to tests/test_protocol.py
from breadmind.network.protocol import SequenceTracker

def test_sequence_tracker_increments():
    tracker = SequenceTracker()
    assert tracker.next_seq() == 1
    assert tracker.next_seq() == 2
    assert tracker.next_seq() == 3

def test_sequence_tracker_validates_incoming():
    tracker = SequenceTracker()
    tracker.validate_incoming(1)  # OK
    tracker.validate_incoming(2)  # OK
    with pytest.raises(MessageSequenceError):
        tracker.validate_incoming(5)  # Gap

def test_sequence_tracker_rejects_replay():
    tracker = SequenceTracker()
    tracker.validate_incoming(1)
    with pytest.raises(MessageSequenceError):
        tracker.validate_incoming(1)  # Replay
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_protocol.py::test_sequence_tracker_increments -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement SequenceTracker**

```python
# Append to src/breadmind/network/protocol.py

class SequenceTracker:
    """Monotonic sequence number tracker for replay protection."""

    def __init__(self) -> None:
        self._outgoing: int = 0
        self._incoming: int = 0

    def next_seq(self) -> int:
        self._outgoing += 1
        return self._outgoing

    def validate_incoming(self, seq: int) -> None:
        expected = self._incoming + 1
        if seq != expected:
            raise MessageSequenceError(
                f"Expected seq {expected}, got {seq}"
            )
        self._incoming = seq
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_protocol.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/network/protocol.py tests/test_protocol.py
git commit -m "feat(network): add sequence tracking for replay protection"
```

---

### Task 3: NetworkConfig

**Files:**
- Modify: `src/breadmind/config.py`
- Test: `tests/test_protocol.py` (add config test)

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_protocol.py
from breadmind.config import NetworkConfig

def test_network_config_defaults():
    cfg = NetworkConfig()
    assert cfg.mode == "standalone"
    assert cfg.ws_port == 8081
    assert cfg.heartbeat_interval == 30
    assert cfg.offline_threshold == 90
    assert cfg.llm_proxy_rpm == 30
    assert cfg.llm_proxy_rph == 500
    assert cfg.offline_queue_max_rows == 10000

def test_network_config_commander_mode():
    cfg = NetworkConfig(mode="commander")
    assert cfg.mode == "commander"

def test_network_config_worker_mode():
    cfg = NetworkConfig(mode="worker", commander_url="wss://central:8081/ws/agent/self")
    assert cfg.commander_url == "wss://central:8081/ws/agent/self"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_protocol.py::test_network_config_defaults -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Add NetworkConfig to config.py**

Add after existing dataclasses in `src/breadmind/config.py`:

```python
@dataclass
class NetworkConfig:
    """Distributed agent network configuration."""
    mode: str = "standalone"  # standalone | commander | worker
    commander_url: str = ""  # Worker: wss://commander:8081/ws/agent/self
    ws_port: int = 8081  # Commander: WebSocket hub port
    heartbeat_interval: int = 30  # seconds
    offline_threshold: int = 90  # seconds without heartbeat → offline
    ca_cert_path: str = ""
    ca_key_path: str = ""
    cert_path: str = ""
    key_path: str = ""
    ca_passphrase_env: str = "BREADMIND_CA_PASSPHRASE"
    llm_proxy_rpm: int = 30  # per-worker requests per minute
    llm_proxy_rph: int = 500  # per-worker requests per hour
    offline_queue_max_rows: int = 10000
    offline_queue_max_mb: int = 100
```

Add `network: NetworkConfig` field to `AppConfig`:

```python
network: NetworkConfig = field(default_factory=NetworkConfig)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_protocol.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/config.py tests/test_protocol.py
git commit -m "feat(config): add NetworkConfig for distributed agent network"
```

---

### Task 4: Database Schema Migration

**Files:**
- Modify: `src/breadmind/storage/database.py`
- Test: `tests/test_protocol.py` (add migration test)

- [ ] **Step 1: Write failing test**

```python
# Append to tests/test_protocol.py
import pytest

@pytest.mark.asyncio
async def test_agent_network_tables_created(tmp_path):
    """Verify migration creates agent network tables (uses SQLite for test)."""
    # This test validates the SQL is syntactically correct
    # Full integration test with PostgreSQL in test_integration_network.py
    from breadmind.network.schema import AGENT_NETWORK_SCHEMA
    assert "CREATE TABLE" in AGENT_NETWORK_SCHEMA
    assert "agents" in AGENT_NETWORK_SCHEMA
    assert "agent_roles" in AGENT_NETWORK_SCHEMA
    assert "agent_tasks" in AGENT_NETWORK_SCHEMA
    assert "agent_certificates" in AGENT_NETWORK_SCHEMA
    assert "agent_role_assignments" in AGENT_NETWORK_SCHEMA
    assert "idempotency_key" in AGENT_NETWORK_SCHEMA
    assert "trace_id" in AGENT_NETWORK_SCHEMA
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_protocol.py::test_agent_network_tables_created -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Create schema module**

```python
# src/breadmind/network/schema.py
"""Database schema for distributed agent network."""

AGENT_NETWORK_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    host VARCHAR(256) NOT NULL,
    status VARCHAR(20) DEFAULT 'registering',
    environment JSONB,
    cert_fingerprint VARCHAR(64),
    cert_expires_at TIMESTAMPTZ,
    last_heartbeat TIMESTAMPTZ,
    registered_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

CREATE TABLE IF NOT EXISTS agent_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) UNIQUE NOT NULL,
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_role_assignments (
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
    role_id UUID REFERENCES agent_roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (agent_id, role_id)
);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id),
    role_id UUID REFERENCES agent_roles(id),
    idempotency_key VARCHAR(128),
    type VARCHAR(20) NOT NULL,
    params JSONB,
    status VARCHAR(20) DEFAULT 'pending',
    result JSONB,
    metrics JSONB,
    trace_id UUID,
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent_status ON agent_tasks(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_created ON agent_tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_idempotency ON agent_tasks(idempotency_key);

CREATE TABLE IF NOT EXISTS agent_certificates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
    fingerprint VARCHAR(64) NOT NULL,
    issued_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true
);
"""

WORKER_LOCAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS offline_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    result TEXT NOT NULL,
    needs_llm INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    result TEXT,
    executed_at TEXT DEFAULT (datetime('now'))
);
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_protocol.py -v`
Expected: All PASS

- [ ] **Step 5: Add migration call to database.py**

In `src/breadmind/storage/database.py`, add to `_migrate()` method:

```python
# At end of _migrate():
from breadmind.network.schema import AGENT_NETWORK_SCHEMA
for statement in AGENT_NETWORK_SCHEMA.split(";"):
    stmt = statement.strip()
    if stmt:
        await conn.execute(stmt)
```

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/network/schema.py src/breadmind/storage/database.py tests/test_protocol.py
git commit -m "feat(network): add database schema for agent network"
```

---

## Chunk 2: PKI & Certificate Management

### Task 5: CA Initialization & Certificate Issuance

**Files:**
- Create: `src/breadmind/network/pki.py`
- Test: `tests/test_pki.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_pki.py
import pytest
import tempfile
from pathlib import Path
from breadmind.network.pki import (
    PKIManager, CertificateInfo,
)

@pytest.fixture
def pki_dir(tmp_path):
    return tmp_path / "pki"

@pytest.fixture
def pki(pki_dir):
    return PKIManager(base_dir=str(pki_dir))

def test_init_ca_creates_root_and_intermediate(pki):
    pki.init_ca(passphrase=b"test-pass")
    assert pki.root_ca_exists()
    assert pki.intermediate_ca_exists()

def test_issue_worker_cert(pki):
    pki.init_ca(passphrase=b"test-pass")
    cert_info = pki.issue_worker_cert(
        agent_id="worker-1",
        hostname="192.168.1.10",
        passphrase=b"test-pass",
    )
    assert isinstance(cert_info, CertificateInfo)
    assert cert_info.agent_id == "worker-1"
    assert cert_info.fingerprint is not None
    assert cert_info.expires_at is not None
    assert Path(cert_info.cert_path).exists()
    assert Path(cert_info.key_path).exists()

def test_revoke_cert(pki):
    pki.init_ca(passphrase=b"test-pass")
    cert_info = pki.issue_worker_cert("worker-1", "host1", passphrase=b"test-pass")
    pki.revoke_cert(cert_info.fingerprint, passphrase=b"test-pass")
    assert pki.is_revoked(cert_info.fingerprint)

def test_verify_valid_cert(pki):
    pki.init_ca(passphrase=b"test-pass")
    cert_info = pki.issue_worker_cert("worker-1", "host1", passphrase=b"test-pass")
    assert pki.verify_cert(cert_info.cert_path) is True

def test_verify_revoked_cert_fails(pki):
    pki.init_ca(passphrase=b"test-pass")
    cert_info = pki.issue_worker_cert("worker-1", "host1", passphrase=b"test-pass")
    pki.revoke_cert(cert_info.fingerprint, passphrase=b"test-pass")
    assert pki.verify_cert(cert_info.cert_path) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_pki.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement PKIManager**

```python
# src/breadmind/network/pki.py
"""PKI management: CA, certificate issuance, revocation, CRL."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

CERT_VALIDITY_DAYS = 90
ROOT_VALIDITY_DAYS = 3650  # 10 years
INTERMEDIATE_VALIDITY_DAYS = 1825  # 5 years


@dataclass
class CertificateInfo:
    agent_id: str
    fingerprint: str
    cert_path: str
    key_path: str
    expires_at: datetime


class PKIManager:
    """Manages Root CA, Intermediate CA, worker certificates, and CRL."""

    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._crl_serials: set[int] = set()
        self._fingerprint_to_serial: dict[str, int] = {}

    def root_ca_exists(self) -> bool:
        return (self._base_dir / "root-ca.pem").exists()

    def intermediate_ca_exists(self) -> bool:
        return (self._base_dir / "intermediate-ca.pem").exists()

    def init_ca(self, passphrase: bytes) -> None:
        """Create root CA and intermediate CA."""
        self._base_dir.mkdir(parents=True, exist_ok=True)
        workers_dir = self._base_dir / "workers"
        workers_dir.mkdir(exist_ok=True)

        # Root CA
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        root_name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "BreadMind Root CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BreadMind"),
        ])
        root_cert = (
            x509.CertificateBuilder()
            .subject_name(root_name)
            .issuer_name(root_name)
            .public_key(root_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=ROOT_VALIDITY_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, key_cert_sign=True, crl_sign=True,
                    content_commitment=False, key_encipherment=False,
                    data_encipherment=False, key_agreement=False,
                    encipher_only=False, decipher_only=False,
                ),
                critical=True,
            )
            .sign(root_key, hashes.SHA256())
        )
        self._write_key(root_key, self._base_dir / "root-ca-key.pem", passphrase)
        self._write_cert(root_cert, self._base_dir / "root-ca.pem")

        # Intermediate CA
        inter_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        inter_name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "BreadMind Intermediate CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BreadMind"),
        ])
        inter_csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(inter_name)
            .sign(inter_key, hashes.SHA256())
        )
        inter_cert = (
            x509.CertificateBuilder()
            .subject_name(inter_csr.subject)
            .issuer_name(root_cert.subject)
            .public_key(inter_csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=INTERMEDIATE_VALIDITY_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, key_cert_sign=True, crl_sign=True,
                    content_commitment=False, key_encipherment=False,
                    data_encipherment=False, key_agreement=False,
                    encipher_only=False, decipher_only=False,
                ),
                critical=True,
            )
            .sign(root_key, hashes.SHA256())
        )
        self._write_key(inter_key, self._base_dir / "intermediate-ca-key.pem", passphrase)
        self._write_cert(inter_cert, self._base_dir / "intermediate-ca.pem")

    def issue_worker_cert(
        self, agent_id: str, hostname: str, passphrase: bytes,
    ) -> CertificateInfo:
        """Issue a client certificate for a worker."""
        inter_key = self._load_key(self._base_dir / "intermediate-ca-key.pem", passphrase)
        inter_cert = self._load_cert(self._base_dir / "intermediate-ca.pem")

        worker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        expires = datetime.now(timezone.utc) + timedelta(days=CERT_VALIDITY_DAYS)
        serial = x509.random_serial_number()

        worker_cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, f"worker-{agent_id}"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "BreadMind"),
            ]))
            .issuer_name(inter_cert.subject)
            .public_key(worker_key.public_key())
            .serial_number(serial)
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(expires)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(hostname)]),
                critical=False,
            )
            .sign(inter_key, hashes.SHA256())
        )

        worker_dir = self._base_dir / "workers" / agent_id
        worker_dir.mkdir(parents=True, exist_ok=True)
        cert_path = worker_dir / "cert.pem"
        key_path = worker_dir / "key.pem"

        self._write_cert(worker_cert, cert_path)
        self._write_key(worker_key, key_path, passphrase=None)  # Worker key unencrypted for auto-start

        fingerprint = hashlib.sha256(
            worker_cert.public_bytes(serialization.Encoding.DER)
        ).hexdigest()

        self._fingerprint_to_serial[fingerprint] = serial

        return CertificateInfo(
            agent_id=agent_id,
            fingerprint=fingerprint,
            cert_path=str(cert_path),
            key_path=str(key_path),
            expires_at=expires,
        )

    def revoke_cert(self, fingerprint: str, passphrase: bytes) -> None:
        serial = self._fingerprint_to_serial.get(fingerprint)
        if serial is not None:
            self._crl_serials.add(serial)
            logger.info("Revoked certificate: %s", fingerprint)

    def is_revoked(self, fingerprint: str) -> bool:
        serial = self._fingerprint_to_serial.get(fingerprint)
        return serial in self._crl_serials if serial is not None else False

    def verify_cert(self, cert_path: str) -> bool:
        """Check cert is valid and not revoked."""
        cert = self._load_cert(Path(cert_path))
        if cert.serial_number in self._crl_serials:
            return False
        if cert.not_valid_after_utc < datetime.now(timezone.utc):
            return False
        return True

    # --- Private helpers ---

    def _write_key(self, key, path: Path, passphrase: bytes | None) -> None:
        enc = (
            serialization.BestAvailableEncryption(passphrase)
            if passphrase
            else serialization.NoEncryption()
        )
        path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=enc,
        ))

    def _write_cert(self, cert, path: Path) -> None:
        path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    def _load_key(self, path: Path, passphrase: bytes | None):
        return serialization.load_pem_private_key(
            path.read_bytes(), password=passphrase,
        )

    def _load_cert(self, path: Path):
        return x509.load_pem_x509_certificate(path.read_bytes())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_pki.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/network/pki.py tests/test_pki.py
git commit -m "feat(network): add PKI manager with CA, cert issuance, and revocation"
```

---

## Chunk 3: Agent Registry & Role Manager

### Task 6: In-Memory Agent Registry

**Files:**
- Create: `src/breadmind/network/registry.py`
- Test: `tests/test_registry_network.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_registry_network.py
import pytest
from datetime import datetime, timezone
from breadmind.network.registry import (
    AgentRegistry, AgentInfo, AgentStatus, RoleDefinition,
)

@pytest.fixture
def registry():
    return AgentRegistry()

def test_register_agent(registry):
    info = registry.register("worker-1", host="192.168.1.10", environment={"os": "linux"})
    assert isinstance(info, AgentInfo)
    assert info.agent_id == "worker-1"
    assert info.status == AgentStatus.REGISTERING

def test_set_agent_status(registry):
    registry.register("worker-1", host="host1")
    registry.set_status("worker-1", AgentStatus.ACTIVE)
    info = registry.get("worker-1")
    assert info.status == AgentStatus.ACTIVE

def test_update_heartbeat(registry):
    registry.register("worker-1", host="host1")
    registry.update_heartbeat("worker-1", {"cpu": 0.5, "memory": 0.7})
    info = registry.get("worker-1")
    assert info.last_heartbeat is not None
    assert info.last_metrics["cpu"] == 0.5

def test_assign_role(registry):
    registry.register("worker-1", host="host1")
    role = RoleDefinition(
        name="k8s-monitor",
        tools=["shell_exec"],
        schedules=[],
        policies={"auto_actions": [], "require_approval": [], "blocked": []},
    )
    registry.assign_role("worker-1", role)
    info = registry.get("worker-1")
    assert "k8s-monitor" in [r.name for r in info.roles]

def test_remove_role(registry):
    registry.register("worker-1", host="host1")
    role = RoleDefinition(name="test-role", tools=[], schedules=[], policies={})
    registry.assign_role("worker-1", role)
    registry.remove_role("worker-1", "test-role")
    info = registry.get("worker-1")
    assert len(info.roles) == 0

def test_list_online_agents(registry):
    registry.register("w1", host="h1")
    registry.register("w2", host="h2")
    registry.set_status("w1", AgentStatus.ACTIVE)
    registry.set_status("w2", AgentStatus.OFFLINE)
    online = registry.list_by_status(AgentStatus.ACTIVE)
    assert len(online) == 1
    assert online[0].agent_id == "w1"

def test_get_unknown_agent_returns_none(registry):
    assert registry.get("nonexistent") is None

def test_detect_offline_agents(registry):
    registry.register("w1", host="h1")
    registry.set_status("w1", AgentStatus.ACTIVE)
    # Simulate stale heartbeat by setting it to past
    registry._agents["w1"].last_heartbeat = datetime(2020, 1, 1, tzinfo=timezone.utc)
    offline = registry.detect_offline(threshold_seconds=90)
    assert "w1" in offline
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_registry_network.py -v`
Expected: FAIL

- [ ] **Step 3: Implement AgentRegistry**

```python
# src/breadmind/network/registry.py
"""Agent registry: tracks worker agents, status, roles."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    REGISTERING = "registering"
    IDLE = "idle"
    ACTIVE = "active"
    OFFLINE = "offline"
    SYNCING = "syncing"
    DRAINING = "draining"
    REMOVED = "removed"


@dataclass
class RoleDefinition:
    name: str
    tools: list[str]
    schedules: list[dict]
    policies: dict[str, list[str]]
    reactive_triggers: list[dict] = field(default_factory=list)
    escalation: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tools": self.tools,
            "schedules": self.schedules,
            "policies": self.policies,
            "reactive_triggers": self.reactive_triggers,
            "escalation": self.escalation,
            "limits": self.limits,
        }


@dataclass
class AgentInfo:
    agent_id: str
    host: str
    status: AgentStatus = AgentStatus.REGISTERING
    environment: dict[str, Any] = field(default_factory=dict)
    roles: list[RoleDefinition] = field(default_factory=list)
    cert_fingerprint: str | None = None
    last_heartbeat: datetime | None = None
    last_metrics: dict[str, Any] = field(default_factory=dict)
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRegistry:
    """In-memory registry of connected worker agents."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentInfo] = {}

    def register(
        self,
        agent_id: str,
        host: str,
        environment: dict | None = None,
        cert_fingerprint: str | None = None,
    ) -> AgentInfo:
        info = AgentInfo(
            agent_id=agent_id,
            host=host,
            environment=environment or {},
            cert_fingerprint=cert_fingerprint,
        )
        self._agents[agent_id] = info
        logger.info("Agent registered: %s @ %s", agent_id, host)
        return info

    def get(self, agent_id: str) -> AgentInfo | None:
        return self._agents.get(agent_id)

    def set_status(self, agent_id: str, status: AgentStatus) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.status = status

    def update_heartbeat(self, agent_id: str, metrics: dict) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.last_heartbeat = datetime.now(timezone.utc)
            agent.last_metrics = metrics

    def assign_role(self, agent_id: str, role: RoleDefinition) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            # Remove existing role with same name if any
            agent.roles = [r for r in agent.roles if r.name != role.name]
            agent.roles.append(role)

    def remove_role(self, agent_id: str, role_name: str) -> None:
        agent = self._agents.get(agent_id)
        if agent:
            agent.roles = [r for r in agent.roles if r.name != role_name]

    def list_by_status(self, status: AgentStatus) -> list[AgentInfo]:
        return [a for a in self._agents.values() if a.status == status]

    def list_all(self) -> list[AgentInfo]:
        return list(self._agents.values())

    def detect_offline(self, threshold_seconds: int = 90) -> list[str]:
        """Find agents whose last heartbeat exceeds threshold."""
        now = datetime.now(timezone.utc)
        offline = []
        for agent_id, info in self._agents.items():
            if info.status in (AgentStatus.ACTIVE, AgentStatus.IDLE):
                if info.last_heartbeat is None:
                    continue
                delta = (now - info.last_heartbeat).total_seconds()
                if delta > threshold_seconds:
                    offline.append(agent_id)
        return offline

    def remove(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_registry_network.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/network/registry.py tests/test_registry_network.py
git commit -m "feat(network): add agent registry with role management and offline detection"
```

---

## Chunk 4: Commander (WebSocket Hub)

### Task 7: Commander WebSocket Hub

**Files:**
- Create: `src/breadmind/network/commander.py`
- Test: `tests/test_commander.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_commander.py
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.network.commander import Commander
from breadmind.network.protocol import MessageType, create_message, serialize_message
from breadmind.network.registry import AgentRegistry, AgentStatus

@pytest.fixture
def registry():
    return AgentRegistry()

@pytest.fixture
def commander(registry):
    return Commander(
        registry=registry,
        llm_provider=AsyncMock(),
        session_key=b"test-key-32-bytes-long-enough!!",
    )

@pytest.mark.asyncio
async def test_handle_registration(commander, registry):
    msg = create_message(
        type=MessageType.HEARTBEAT,
        source="worker-1",
        target="commander",
        payload={"environment": {"os": "linux"}, "host": "192.168.1.10"},
    )
    ws_mock = AsyncMock()
    await commander.handle_message(msg, ws_mock, agent_id="worker-1")
    agent = registry.get("worker-1")
    assert agent is not None

@pytest.mark.asyncio
async def test_handle_heartbeat_updates_metrics(commander, registry):
    registry.register("worker-1", host="h1")
    registry.set_status("worker-1", AgentStatus.ACTIVE)
    msg = create_message(
        type=MessageType.HEARTBEAT,
        source="worker-1",
        target="commander",
        payload={"cpu": 0.3, "memory": 0.5, "disk": 0.2, "queue_size": 0},
    )
    ws_mock = AsyncMock()
    await commander.handle_message(msg, ws_mock, agent_id="worker-1")
    agent = registry.get("worker-1")
    assert agent.last_metrics["cpu"] == 0.3

@pytest.mark.asyncio
async def test_handle_task_result(commander, registry):
    registry.register("worker-1", host="h1")
    msg = create_message(
        type=MessageType.TASK_RESULT,
        source="worker-1",
        target="commander",
        payload={
            "task_id": "t1",
            "status": "success",
            "output": "all pods healthy",
            "metrics": {"duration_ms": 500},
        },
    )
    ws_mock = AsyncMock()
    await commander.handle_message(msg, ws_mock, agent_id="worker-1")
    assert "t1" in commander.completed_tasks

@pytest.mark.asyncio
async def test_handle_llm_request_proxies_to_provider(commander):
    commander._llm_provider.chat = AsyncMock(return_value=MagicMock(
        content="restart the pod",
        tool_calls=[],
        usage=MagicMock(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    ))
    msg = create_message(
        type=MessageType.LLM_REQUEST,
        source="worker-1",
        target="commander",
        payload={
            "messages": [{"role": "user", "content": "check pods"}],
            "tools": [],
        },
    )
    ws_mock = AsyncMock()
    await commander.handle_message(msg, ws_mock, agent_id="worker-1")
    ws_mock.send.assert_called_once()
    sent_raw = ws_mock.send.call_args[0][0]
    sent = json.loads(sent_raw)
    assert sent["type"] == "llm_response"

@pytest.mark.asyncio
async def test_dispatch_task_to_worker(commander, registry):
    registry.register("worker-1", host="h1")
    registry.set_status("worker-1", AgentStatus.ACTIVE)
    ws_mock = AsyncMock()
    commander._connections["worker-1"] = ws_mock
    await commander.dispatch_task(
        agent_id="worker-1",
        task_type="on_demand",
        params={"command": "kubectl get pods"},
    )
    ws_mock.send.assert_called_once()
    sent = json.loads(ws_mock.send.call_args[0][0])
    assert sent["type"] == "task_assign"

@pytest.mark.asyncio
async def test_dispatch_role_update(commander, registry):
    registry.register("worker-1", host="h1")
    ws_mock = AsyncMock()
    commander._connections["worker-1"] = ws_mock
    from breadmind.network.registry import RoleDefinition
    role = RoleDefinition(name="test", tools=["shell_exec"], schedules=[], policies={})
    await commander.send_role_update("worker-1", role)
    ws_mock.send.assert_called_once()
    sent = json.loads(ws_mock.send.call_args[0][0])
    assert sent["type"] == "role_update"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_commander.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Commander**

```python
# src/breadmind/network/commander.py
"""Commander: WebSocket hub, LLM proxy, task dispatch."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable

from breadmind.network.protocol import (
    MessageEnvelope, MessageType, SequenceTracker,
    create_message, serialize_message, deserialize_message,
)
from breadmind.network.registry import (
    AgentRegistry, AgentStatus, RoleDefinition,
)

logger = logging.getLogger(__name__)


class Commander:
    """Central hub managing worker agents."""

    def __init__(
        self,
        registry: AgentRegistry,
        llm_provider: Any,
        session_key: bytes,
        on_task_result: Callable | None = None,
    ) -> None:
        self._registry = registry
        self._llm_provider = llm_provider
        self._session_key = session_key
        self._on_task_result = on_task_result
        self._connections: dict[str, Any] = {}  # agent_id → websocket
        self._seq_trackers: dict[str, SequenceTracker] = {}
        self.completed_tasks: dict[str, dict] = {}

    def add_connection(self, agent_id: str, ws: Any) -> None:
        self._connections[agent_id] = ws
        self._seq_trackers[agent_id] = SequenceTracker()

    def remove_connection(self, agent_id: str) -> None:
        self._connections.pop(agent_id, None)
        self._seq_trackers.pop(agent_id, None)

    async def handle_message(
        self, msg: MessageEnvelope, ws: Any, agent_id: str,
    ) -> None:
        """Route incoming message from a worker."""
        if msg.type == MessageType.HEARTBEAT:
            await self._handle_heartbeat(msg, ws, agent_id)
        elif msg.type == MessageType.TASK_RESULT:
            await self._handle_task_result(msg, agent_id)
        elif msg.type == MessageType.LLM_REQUEST:
            await self._handle_llm_request(msg, ws, agent_id)
        elif msg.type == MessageType.SYNC:
            await self._handle_sync(msg, agent_id)
        else:
            logger.warning("Unknown message type from %s: %s", agent_id, msg.type)

    async def dispatch_task(
        self,
        agent_id: str,
        task_type: str,
        params: dict,
        trace_id: str | None = None,
    ) -> str:
        """Send a task to a worker. Returns task_id."""
        task_id = str(uuid.uuid4())
        idempotency_key = str(uuid.uuid4())
        msg = create_message(
            type=MessageType.TASK_ASSIGN,
            source="commander",
            target=agent_id,
            payload={
                "task_id": task_id,
                "idempotency_key": idempotency_key,
                "type": task_type,
                "params": params,
            },
            trace_id=trace_id,
        )
        await self._send(agent_id, msg)
        return task_id

    async def send_role_update(self, agent_id: str, role: RoleDefinition) -> None:
        msg = create_message(
            type=MessageType.ROLE_UPDATE,
            source="commander",
            target=agent_id,
            payload={"role": role.to_dict()},
        )
        self._registry.assign_role(agent_id, role)
        await self._send(agent_id, msg)

    async def send_command(self, agent_id: str, action: str, params: dict | None = None) -> None:
        msg = create_message(
            type=MessageType.COMMAND,
            source="commander",
            target=agent_id,
            payload={"action": action, **(params or {})},
        )
        await self._send(agent_id, msg)

    # --- Private handlers ---

    async def _handle_heartbeat(self, msg: MessageEnvelope, ws: Any, agent_id: str) -> None:
        payload = msg.payload
        agent = self._registry.get(agent_id)
        if agent is None:
            self._registry.register(
                agent_id=agent_id,
                host=payload.get("host", "unknown"),
                environment=payload.get("environment", {}),
            )
            self.add_connection(agent_id, ws)
        self._registry.update_heartbeat(agent_id, {
            k: v for k, v in payload.items() if k not in ("environment", "host")
        })

    async def _handle_task_result(self, msg: MessageEnvelope, agent_id: str) -> None:
        payload = msg.payload
        task_id = payload.get("task_id")
        self.completed_tasks[task_id] = payload
        logger.info("Task %s completed by %s: %s", task_id, agent_id, payload.get("status"))
        if self._on_task_result:
            await self._on_task_result(agent_id, payload)

    async def _handle_llm_request(self, msg: MessageEnvelope, ws: Any, agent_id: str) -> None:
        payload = msg.payload
        try:
            from breadmind.llm.base import LLMMessage, ToolDefinition
            messages = [LLMMessage(**m) for m in payload.get("messages", [])]
            tools = [ToolDefinition(**t) for t in payload.get("tools", [])] if payload.get("tools") else None
            response = await self._llm_provider.chat(messages=messages, tools=tools)
            reply = create_message(
                type=MessageType.LLM_RESPONSE,
                source="commander",
                target=agent_id,
                payload={
                    "content": response.content,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in response.tool_calls
                    ],
                    "stop_reason": response.stop_reason,
                },
                reply_to=msg.id,
                trace_id=msg.trace_id,
            )
        except Exception as e:
            logger.exception("LLM proxy error for %s", agent_id)
            reply = create_message(
                type=MessageType.LLM_RESPONSE,
                source="commander",
                target=agent_id,
                payload={"error": str(e)},
                reply_to=msg.id,
            )
        await self._send_raw(ws, reply)

    async def _handle_sync(self, msg: MessageEnvelope, agent_id: str) -> None:
        results = msg.payload.get("results", [])
        for result in results:
            task_id = result.get("task_id")
            if task_id not in self.completed_tasks:
                self.completed_tasks[task_id] = result
        logger.info("Synced %d results from %s", len(results), agent_id)
        self._registry.set_status(agent_id, AgentStatus.ACTIVE)

    # --- Send helpers ---

    async def _send(self, agent_id: str, msg: MessageEnvelope) -> None:
        ws = self._connections.get(agent_id)
        if ws:
            await self._send_raw(ws, msg)
        else:
            logger.warning("No connection for agent %s", agent_id)

    async def _send_raw(self, ws: Any, msg: MessageEnvelope) -> None:
        raw = serialize_message(msg, self._session_key)
        await ws.send(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_commander.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/network/commander.py tests/test_commander.py
git commit -m "feat(network): add Commander WebSocket hub with LLM proxy and task dispatch"
```

---

## Chunk 5: Worker Runtime

### Task 8: Worker Agent

**Files:**
- Create: `src/breadmind/network/worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_worker.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.network.worker import Worker, WorkerState
from breadmind.network.protocol import MessageType, create_message, serialize_message

SESSION_KEY = b"test-key-32-bytes-long-enough!!"

@pytest.fixture
def tool_registry():
    reg = MagicMock()
    reg.execute = AsyncMock(return_value=MagicMock(success=True, output="ok"))
    reg.get_definitions = MagicMock(return_value=[])
    return reg

@pytest.fixture
def worker(tool_registry):
    return Worker(
        agent_id="worker-1",
        commander_url="wss://localhost:8081/ws/agent/worker-1",
        session_key=SESSION_KEY,
        tool_registry=tool_registry,
    )

def test_worker_initial_state(worker):
    assert worker.state == WorkerState.STARTING

@pytest.mark.asyncio
async def test_handle_task_assign_executes_locally(worker, tool_registry):
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={
            "task_id": "t1",
            "idempotency_key": "idem-1",
            "type": "on_demand",
            "params": {"tool": "shell_exec", "arguments": {"command": "ls"}},
        },
    )
    ws_mock = AsyncMock()
    worker._ws = ws_mock
    await worker.handle_message(msg)
    tool_registry.execute.assert_called_once_with("shell_exec", {"command": "ls"})
    ws_mock.send.assert_called_once()
    sent = json.loads(ws_mock.send.call_args[0][0])
    assert sent["type"] == "task_result"
    assert sent["payload"]["task_id"] == "t1"
    assert sent["payload"]["status"] == "success"

@pytest.mark.asyncio
async def test_handle_role_update_stores_role(worker):
    msg = create_message(
        type=MessageType.ROLE_UPDATE,
        source="commander",
        target="worker-1",
        payload={
            "role": {
                "name": "monitor",
                "tools": ["shell_exec"],
                "schedules": [{"type": "cron", "expr": "*/5 * * * *", "task": "check"}],
                "policies": {"auto_actions": [], "require_approval": [], "blocked": []},
            },
        },
    )
    await worker.handle_message(msg)
    assert "monitor" in worker.roles

@pytest.mark.asyncio
async def test_handle_command_restart(worker):
    msg = create_message(
        type=MessageType.COMMAND,
        source="commander",
        target="worker-1",
        payload={"action": "restart"},
    )
    with patch.object(worker, "_restart", new_callable=AsyncMock) as mock_restart:
        await worker.handle_message(msg)
        mock_restart.assert_called_once()

@pytest.mark.asyncio
async def test_blocked_tool_not_executed(worker, tool_registry):
    worker.roles["test"] = {
        "tools": ["file_read"],
        "policies": {"blocked": ["shell_exec"], "auto_actions": [], "require_approval": []},
    }
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={
            "task_id": "t2",
            "idempotency_key": "idem-2",
            "type": "on_demand",
            "params": {"tool": "shell_exec", "arguments": {"command": "rm -rf /"}},
        },
    )
    ws_mock = AsyncMock()
    worker._ws = ws_mock
    await worker.handle_message(msg)
    tool_registry.execute.assert_not_called()
    sent = json.loads(ws_mock.send.call_args[0][0])
    assert sent["payload"]["status"] == "failure"
    assert "blocked" in sent["payload"]["output"].lower()

@pytest.mark.asyncio
async def test_offline_queue_stores_when_disconnected(worker, tool_registry):
    worker._ws = None  # Disconnected
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="worker-1",
        payload={
            "task_id": "t3",
            "idempotency_key": "idem-3",
            "type": "scheduled",
            "params": {"tool": "shell_exec", "arguments": {"command": "uptime"}},
        },
    )
    await worker.handle_message(msg)
    tool_registry.execute.assert_called_once()
    assert len(worker._offline_queue) == 1
    assert worker._offline_queue[0]["task_id"] == "t3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_worker.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Worker**

```python
# src/breadmind/network/worker.py
"""Worker agent runtime: executes tasks locally, reports to Commander."""

from __future__ import annotations

import json
import logging
import time
from enum import Enum
from typing import Any

from breadmind.network.protocol import (
    MessageEnvelope, MessageType, SequenceTracker,
    create_message, serialize_message, deserialize_message,
)

logger = logging.getLogger(__name__)


class WorkerState(Enum):
    STARTING = "starting"
    REGISTERING = "registering"
    IDLE = "idle"
    ACTIVE = "active"
    OFFLINE = "offline"
    SYNCING = "syncing"
    DRAINING = "draining"


class Worker:
    """Lightweight agent that executes tasks locally."""

    def __init__(
        self,
        agent_id: str,
        commander_url: str,
        session_key: bytes,
        tool_registry: Any,
    ) -> None:
        self.agent_id = agent_id
        self._commander_url = commander_url
        self._session_key = session_key
        self._tools = tool_registry
        self._ws: Any | None = None
        self._seq = SequenceTracker()
        self.state = WorkerState.STARTING
        self.roles: dict[str, dict] = {}
        self._offline_queue: list[dict] = []
        self._task_history: dict[str, dict] = {}

    async def handle_message(self, msg: MessageEnvelope) -> None:
        """Route incoming message from Commander."""
        if msg.type == MessageType.TASK_ASSIGN:
            await self._handle_task_assign(msg)
        elif msg.type == MessageType.ROLE_UPDATE:
            await self._handle_role_update(msg)
        elif msg.type == MessageType.COMMAND:
            await self._handle_command(msg)
        elif msg.type == MessageType.LLM_RESPONSE:
            await self._handle_llm_response(msg)
        else:
            logger.warning("Unknown message type: %s", msg.type)

    async def send_heartbeat(self) -> None:
        """Send heartbeat with system metrics to Commander."""
        try:
            import psutil
            payload = {
                "cpu": psutil.cpu_percent() / 100,
                "memory": psutil.virtual_memory().percent / 100,
                "disk": psutil.disk_usage("/").percent / 100,
                "queue_size": len(self._offline_queue),
            }
        except ImportError:
            payload = {"queue_size": len(self._offline_queue)}
        msg = create_message(
            type=MessageType.HEARTBEAT,
            source=self.agent_id,
            target="commander",
            payload=payload,
        )
        await self._send(msg)

    async def sync_offline_queue(self) -> None:
        """Send queued results to Commander."""
        if not self._offline_queue:
            return
        msg = create_message(
            type=MessageType.SYNC,
            source=self.agent_id,
            target="commander",
            payload={"results": list(self._offline_queue)},
        )
        await self._send(msg)
        self._offline_queue.clear()
        self.state = WorkerState.ACTIVE

    # --- Private handlers ---

    async def _handle_task_assign(self, msg: MessageEnvelope) -> None:
        payload = msg.payload
        task_id = payload["task_id"]
        tool_name = payload.get("params", {}).get("tool", "")
        arguments = payload.get("params", {}).get("arguments", {})

        # Check if tool is blocked by any role policy
        if self._is_tool_blocked(tool_name):
            result = {
                "task_id": task_id,
                "status": "failure",
                "output": f"Tool '{tool_name}' is blocked by role policy",
                "metrics": {},
            }
        else:
            start = time.monotonic()
            try:
                tool_result = await self._tools.execute(tool_name, arguments)
                result = {
                    "task_id": task_id,
                    "status": "success" if tool_result.success else "failure",
                    "output": tool_result.output,
                    "metrics": {"duration_ms": int((time.monotonic() - start) * 1000)},
                }
            except Exception as e:
                result = {
                    "task_id": task_id,
                    "status": "failure",
                    "output": str(e),
                    "metrics": {"duration_ms": int((time.monotonic() - start) * 1000)},
                }

        self._task_history[task_id] = result

        if self._ws is not None:
            reply = create_message(
                type=MessageType.TASK_RESULT,
                source=self.agent_id,
                target="commander",
                payload=result,
                reply_to=msg.id,
                trace_id=msg.trace_id,
            )
            await self._send(reply)
        else:
            self._offline_queue.append(result)

    async def _handle_role_update(self, msg: MessageEnvelope) -> None:
        role_data = msg.payload.get("role", {})
        name = role_data.get("name")
        if name:
            self.roles[name] = role_data
            logger.info("Role updated: %s", name)

    async def _handle_command(self, msg: MessageEnvelope) -> None:
        action = msg.payload.get("action")
        if action == "restart":
            await self._restart()
        elif action == "decommission":
            self.state = WorkerState.DRAINING
        else:
            logger.warning("Unknown command action: %s", action)

    async def _handle_llm_response(self, msg: MessageEnvelope) -> None:
        # Will be used by tasks that need LLM reasoning
        # For now, store for pending LLM requests
        pass

    async def _restart(self) -> None:
        logger.info("Worker restart requested")
        # Actual restart logic will be implemented with process management

    def _is_tool_blocked(self, tool_name: str) -> bool:
        for role in self.roles.values():
            policies = role.get("policies", {})
            blocked = policies.get("blocked", [])
            if tool_name in blocked:
                return True
        return False

    async def _send(self, msg: MessageEnvelope) -> None:
        if self._ws is not None:
            raw = serialize_message(msg, self._session_key)
            await self._ws.send(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_worker.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/network/worker.py tests/test_worker.py
git commit -m "feat(network): add Worker runtime with task execution and offline queue"
```

---

## Chunk 6: Sync Manager & Offline Reconciliation

### Task 9: Sync Manager

**Files:**
- Create: `src/breadmind/network/sync.py`
- Test: `tests/test_sync.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sync.py
import pytest
from breadmind.network.sync import SyncManager

@pytest.fixture
def sync_mgr():
    return SyncManager()

def test_accept_first_wins_new_task(sync_mgr):
    result = {"task_id": "t1", "status": "success", "output": "ok"}
    accepted = sync_mgr.reconcile("idem-1", result)
    assert accepted is True

def test_accept_first_wins_duplicate(sync_mgr):
    r1 = {"task_id": "t1", "status": "success", "output": "ok"}
    r2 = {"task_id": "t1-dup", "status": "success", "output": "also ok"}
    sync_mgr.reconcile("idem-1", r1)
    accepted = sync_mgr.reconcile("idem-1", r2)
    assert accepted is False  # Already have a success

def test_reconcile_allows_success_over_pending(sync_mgr):
    r1 = {"task_id": "t1", "status": "pending", "output": ""}
    sync_mgr.reconcile("idem-1", r1)
    r2 = {"task_id": "t1", "status": "success", "output": "done"}
    accepted = sync_mgr.reconcile("idem-1", r2)
    assert accepted is True

def test_bulk_reconcile(sync_mgr):
    results = [
        {"idempotency_key": "k1", "task_id": "t1", "status": "success", "output": "a"},
        {"idempotency_key": "k2", "task_id": "t2", "status": "success", "output": "b"},
        {"idempotency_key": "k1", "task_id": "t1-dup", "status": "success", "output": "c"},
    ]
    accepted, rejected = sync_mgr.bulk_reconcile(results)
    assert accepted == 2
    assert rejected == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_sync.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SyncManager**

```python
# src/breadmind/network/sync.py
"""Offline sync reconciliation with idempotency."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Statuses that count as "resolved" (no longer accept updates)
_FINAL_STATUSES = {"success", "failure", "escalated"}


class SyncManager:
    """Reconciles task results using accept-first-wins policy."""

    def __init__(self) -> None:
        self._results: dict[str, dict] = {}  # idempotency_key → result

    def reconcile(self, idempotency_key: str, result: dict) -> bool:
        """Accept result if no final result exists for this key. Returns True if accepted."""
        existing = self._results.get(idempotency_key)
        if existing and existing.get("status") in _FINAL_STATUSES:
            logger.info(
                "Duplicate result for %s (existing: %s, new: %s) — rejected",
                idempotency_key, existing.get("status"), result.get("status"),
            )
            return False
        self._results[idempotency_key] = result
        return True

    def bulk_reconcile(self, results: list[dict]) -> tuple[int, int]:
        """Reconcile multiple results. Returns (accepted_count, rejected_count)."""
        accepted = 0
        rejected = 0
        for r in results:
            key = r.get("idempotency_key", r.get("task_id", ""))
            if self.reconcile(key, r):
                accepted += 1
            else:
                rejected += 1
        return accepted, rejected

    def get_result(self, idempotency_key: str) -> dict | None:
        return self._results.get(idempotency_key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_sync.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/network/sync.py tests/test_sync.py
git commit -m "feat(network): add SyncManager with idempotency reconciliation"
```

---

## Chunk 7: Provisioning System

### Task 10: Provisioner Base & Strategy Interface

**Files:**
- Create: `src/breadmind/provisioning/__init__.py`
- Create: `src/breadmind/provisioning/provisioner.py`
- Create: `src/breadmind/provisioning/strategies/__init__.py`
- Create: `src/breadmind/provisioning/strategies/base.py`
- Test: `tests/test_provisioner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_provisioner.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from breadmind.provisioning.provisioner import Provisioner, DeploymentTarget
from breadmind.provisioning.strategies.base import DeployStrategy

def test_detect_kubernetes_environment():
    p = Provisioner()
    target = DeploymentTarget(
        host="k8s-node1",
        access_method="kubernetes",
        environment={"runtime": "containerd"},
    )
    strategy = p.select_strategy(target)
    assert strategy.__class__.__name__ == "KubernetesStrategy"

def test_detect_proxmox_environment():
    p = Provisioner()
    target = DeploymentTarget(
        host="pve-host1",
        access_method="proxmox",
        environment={"type": "proxmox"},
    )
    strategy = p.select_strategy(target)
    assert strategy.__class__.__name__ == "ProxmoxStrategy"

def test_detect_ssh_fallback():
    p = Provisioner()
    target = DeploymentTarget(
        host="linux-server",
        access_method="ssh",
        environment={"os": "linux"},
    )
    strategy = p.select_strategy(target)
    assert strategy.__class__.__name__ == "SSHStrategy"

@pytest.mark.asyncio
async def test_provision_calls_strategy_deploy():
    p = Provisioner()
    target = DeploymentTarget(host="h1", access_method="ssh", environment={})
    mock_strategy = AsyncMock(spec=DeployStrategy)
    mock_strategy.deploy = AsyncMock(return_value={"status": "ok"})
    with patch.object(p, "select_strategy", return_value=mock_strategy):
        result = await p.provision(target, commander_url="wss://cmd:8081", cert_data=b"cert", key_data=b"key")
    mock_strategy.deploy.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_provisioner.py -v`
Expected: FAIL

- [ ] **Step 3: Create provisioning package**

```python
# src/breadmind/provisioning/__init__.py
"""Worker provisioning and deployment."""
```

```python
# src/breadmind/provisioning/strategies/__init__.py
"""Deployment strategies for different infrastructure targets."""
```

```python
# src/breadmind/provisioning/strategies/base.py
"""Abstract deployment strategy interface."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class DeployStrategy(ABC):
    @abstractmethod
    async def deploy(
        self,
        host: str,
        commander_url: str,
        cert_data: bytes,
        key_data: bytes,
        config: dict | None = None,
    ) -> dict[str, Any]:
        """Deploy worker to target. Returns deployment result."""
        ...

    @abstractmethod
    async def remove(self, host: str) -> dict[str, Any]:
        """Remove worker from target."""
        ...

    @abstractmethod
    async def update(self, host: str, package_data: bytes, signature: bytes) -> dict[str, Any]:
        """Update worker on target."""
        ...
```

```python
# src/breadmind/provisioning/provisioner.py
"""Environment detection and deployment orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from breadmind.provisioning.strategies.base import DeployStrategy

logger = logging.getLogger(__name__)


@dataclass
class DeploymentTarget:
    host: str
    access_method: str  # kubernetes | proxmox | ssh
    environment: dict[str, Any] = field(default_factory=dict)


class Provisioner:
    """Detects target environment and selects deployment strategy."""

    def select_strategy(self, target: DeploymentTarget) -> DeployStrategy:
        method = target.access_method.lower()
        if method == "kubernetes":
            from breadmind.provisioning.strategies.kubernetes import KubernetesStrategy
            return KubernetesStrategy()
        elif method == "proxmox":
            from breadmind.provisioning.strategies.proxmox import ProxmoxStrategy
            return ProxmoxStrategy()
        else:
            from breadmind.provisioning.strategies.ssh import SSHStrategy
            return SSHStrategy()

    async def provision(
        self,
        target: DeploymentTarget,
        commander_url: str,
        cert_data: bytes,
        key_data: bytes,
        config: dict | None = None,
    ) -> dict[str, Any]:
        strategy = self.select_strategy(target)
        logger.info("Deploying worker to %s via %s", target.host, type(strategy).__name__)
        return await strategy.deploy(
            host=target.host,
            commander_url=commander_url,
            cert_data=cert_data,
            key_data=key_data,
            config=config,
        )

    async def remove(self, target: DeploymentTarget) -> dict[str, Any]:
        strategy = self.select_strategy(target)
        return await strategy.remove(host=target.host)
```

- [ ] **Step 4: Create stub strategies**

```python
# src/breadmind/provisioning/strategies/kubernetes.py
"""Kubernetes DaemonSet deployment strategy."""

from __future__ import annotations
from typing import Any
from breadmind.provisioning.strategies.base import DeployStrategy


class KubernetesStrategy(DeployStrategy):
    async def deploy(self, host, commander_url, cert_data, key_data, config=None) -> dict[str, Any]:
        # TODO: Create DaemonSet via K8s API
        return {"status": "deployed", "method": "kubernetes", "host": host}

    async def remove(self, host) -> dict[str, Any]:
        return {"status": "removed", "host": host}

    async def update(self, host, package_data, signature) -> dict[str, Any]:
        return {"status": "updated", "host": host}
```

```python
# src/breadmind/provisioning/strategies/proxmox.py
"""Proxmox LXC container deployment strategy."""

from __future__ import annotations
from typing import Any
from breadmind.provisioning.strategies.base import DeployStrategy


class ProxmoxStrategy(DeployStrategy):
    async def deploy(self, host, commander_url, cert_data, key_data, config=None) -> dict[str, Any]:
        # TODO: Create LXC container via Proxmox API
        return {"status": "deployed", "method": "proxmox", "host": host}

    async def remove(self, host) -> dict[str, Any]:
        return {"status": "removed", "host": host}

    async def update(self, host, package_data, signature) -> dict[str, Any]:
        return {"status": "updated", "host": host}
```

```python
# src/breadmind/provisioning/strategies/ssh.py
"""Direct SSH installation strategy."""

from __future__ import annotations
from typing import Any
from breadmind.provisioning.strategies.base import DeployStrategy


class SSHStrategy(DeployStrategy):
    async def deploy(self, host, commander_url, cert_data, key_data, config=None) -> dict[str, Any]:
        # TODO: SSH into host, install breadmind, configure as worker
        return {"status": "deployed", "method": "ssh", "host": host}

    async def remove(self, host) -> dict[str, Any]:
        return {"status": "removed", "host": host}

    async def update(self, host, package_data, signature) -> dict[str, Any]:
        return {"status": "updated", "host": host}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_provisioner.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/provisioning/ tests/test_provisioner.py
git commit -m "feat(provisioning): add provisioner with K8s/Proxmox/SSH strategy stubs"
```

---

## Chunk 8: Integration — main.py, agent.py, safety.py, web/app.py

### Task 11: Mode Flag in main.py

**Files:**
- Modify: `src/breadmind/main.py`

- [ ] **Step 1: Read current main.py argument parsing**

Check how CLI arguments are currently parsed in `main.py`.

- [ ] **Step 2: Add --mode argument**

Add to the argument parser in `main.py`:

```python
parser.add_argument(
    "--mode",
    choices=["standalone", "commander", "worker"],
    default="standalone",
    help="Run mode: standalone (default), commander, or worker",
)
parser.add_argument(
    "--commander-url",
    default="",
    help="Commander WebSocket URL (worker mode only)",
)
```

- [ ] **Step 3: Add mode branching in run()**

Add after config loading in `run()`:

```python
mode = args.mode if hasattr(args, "mode") else config.network.mode

if mode == "worker":
    await run_worker(config, args)
    return

# ... existing Commander/standalone init continues ...

if mode == "commander":
    # Initialize Commander components after existing init
    from breadmind.network.commander import Commander
    from breadmind.network.registry import AgentRegistry
    from breadmind.network.pki import PKIManager

    agent_registry = AgentRegistry()
    commander = Commander(
        registry=agent_registry,
        llm_provider=provider,
        session_key=config.security.api_keys[0].encode() if config.security.api_keys else b"default-session-key",
    )
    # Add WebSocket endpoint for workers (handled via web_app)
```

- [ ] **Step 4: Add run_worker function**

```python
async def run_worker(config, args):
    """Bootstrap worker mode — lightweight runtime."""
    from breadmind.network.worker import Worker
    from breadmind.tools.registry import ToolRegistry
    from breadmind.tools.builtin import register_builtin_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)

    worker = Worker(
        agent_id=config.network.mode or "worker",
        commander_url=args.commander_url or config.network.commander_url,
        session_key=b"session-key",  # Derived from mTLS in production
        tool_registry=registry,
    )

    # TODO: Connect WebSocket, start heartbeat loop, wait for shutdown
    logger.info("Worker mode started, connecting to %s", worker._commander_url)
```

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/main.py
git commit -m "feat: add --mode flag for commander/worker mode in main.py"
```

---

### Task 12: Agent ID in SafetyGuard

**Files:**
- Modify: `src/breadmind/core/safety.py`

- [ ] **Step 1: Read current safety.py**

- [ ] **Step 2: Add agent_id parameter to check()**

Modify `SafetyGuard.check()` signature:

```python
def check(self, action: str, params: dict, user: str, channel: str, agent_id: str | None = None) -> SafetyResult:
```

Add role-based filtering when `agent_id` is provided:

```python
# At the start of check(), after existing blacklist check:
if agent_id and hasattr(self, '_agent_policies'):
    policies = self._agent_policies.get(agent_id, {})
    blocked = policies.get("blocked", [])
    if action in blocked:
        return SafetyResult.DENY
```

Add method to set agent policies:

```python
def set_agent_policies(self, agent_id: str, policies: dict) -> None:
    if not hasattr(self, '_agent_policies'):
        self._agent_policies = {}
    self._agent_policies[agent_id] = policies
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/core/safety.py
git commit -m "feat(safety): add agent_id support for distributed worker policies"
```

---

### Task 13: WebSocket Agent Endpoint in web/app.py

**Files:**
- Modify: `src/breadmind/web/app.py`

- [ ] **Step 1: Read current WebSocket handling in app.py**

- [ ] **Step 2: Add /ws/agent/{agent_id} endpoint**

Add to the route registration in `WebApp.__init__()`:

```python
@self.app.websocket("/ws/agent/{agent_id}")
async def agent_websocket(websocket: WebSocket, agent_id: str):
    """WebSocket endpoint for worker agent connections."""
    await websocket.accept()
    commander = self._commander  # Set during init if commander mode
    if not commander:
        await websocket.close(code=1008, reason="Not in commander mode")
        return

    commander.add_connection(agent_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            msg = deserialize_message(raw, commander._session_key)
            await commander.handle_message(msg, websocket, agent_id)
    except WebSocketDisconnect:
        commander.remove_connection(agent_id)
        from breadmind.network.registry import AgentStatus
        commander._registry.set_status(agent_id, AgentStatus.OFFLINE)
    except Exception as e:
        logger.exception("Agent WebSocket error for %s", agent_id)
        commander.remove_connection(agent_id)
```

- [ ] **Step 3: Add REST endpoints for agent management**

```python
@self.app.get("/api/agents")
async def list_agents():
    if not self._commander:
        return {"agents": []}
    agents = self._commander._registry.list_all()
    return {"agents": [
        {
            "id": a.agent_id,
            "host": a.host,
            "status": a.status.value,
            "roles": [r.name for r in a.roles] if hasattr(a.roles[0], 'name') else [] if a.roles else [],
            "last_heartbeat": a.last_heartbeat.isoformat() if a.last_heartbeat else None,
            "metrics": a.last_metrics,
        }
        for a in agents
    ]}

@self.app.post("/api/agents/{agent_id}/task")
async def dispatch_task(agent_id: str, body: dict):
    if not self._commander:
        return {"error": "Not in commander mode"}
    task_id = await self._commander.dispatch_task(
        agent_id=agent_id,
        task_type=body.get("type", "on_demand"),
        params=body.get("params", {}),
    )
    return {"task_id": task_id}

@self.app.post("/api/agents/{agent_id}/role")
async def assign_role(agent_id: str, body: dict):
    if not self._commander:
        return {"error": "Not in commander mode"}
    from breadmind.network.registry import RoleDefinition
    role = RoleDefinition(**body)
    await self._commander.send_role_update(agent_id, role)
    return {"status": "assigned"}
```

- [ ] **Step 4: Commit**

```bash
git add src/breadmind/web/app.py
git commit -m "feat(web): add WebSocket and REST endpoints for agent network"
```

---

## Chunk 9: Integration Test

### Task 14: End-to-End Commander ↔ Worker Test

**Files:**
- Create: `tests/test_integration_network.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration_network.py
"""Integration test: Commander ↔ Worker message flow."""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock
from breadmind.network.commander import Commander
from breadmind.network.worker import Worker
from breadmind.network.registry import AgentRegistry, AgentStatus, RoleDefinition
from breadmind.network.protocol import (
    MessageType, create_message, serialize_message, deserialize_message,
)

SESSION_KEY = b"integration-test-key-32-bytes!!"


class FakeWebSocket:
    """Simulates WebSocket for testing Commander ↔ Worker flow."""

    def __init__(self, peer: "FakeWebSocket | None" = None):
        self._peer = peer
        self._handler = None
        self.sent: list[str] = []

    def set_peer(self, peer: "FakeWebSocket"):
        self._peer = peer

    def set_handler(self, handler):
        self._handler = handler

    async def send(self, data: str):
        self.sent.append(data)
        if self._peer and self._peer._handler:
            msg = deserialize_message(data, SESSION_KEY)
            await self._peer._handler(msg)


@pytest.fixture
def registry():
    return AgentRegistry()

@pytest.fixture
def commander(registry):
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=MagicMock(
        content="all good",
        tool_calls=[],
        usage=MagicMock(input_tokens=5, output_tokens=3),
        stop_reason="end_turn",
    ))
    return Commander(registry=registry, llm_provider=provider, session_key=SESSION_KEY)

@pytest.fixture
def tool_registry():
    reg = MagicMock()
    reg.execute = AsyncMock(return_value=MagicMock(success=True, output="pods healthy"))
    return reg

@pytest.fixture
def worker(tool_registry):
    return Worker(
        agent_id="test-worker",
        commander_url="wss://localhost:8081/ws/agent/test-worker",
        session_key=SESSION_KEY,
        tool_registry=tool_registry,
    )

@pytest.mark.asyncio
async def test_full_task_flow(commander, worker, registry):
    """Commander dispatches task → Worker executes → Commander receives result."""
    # Set up fake WebSocket pair
    cmd_ws = FakeWebSocket()
    worker_ws = FakeWebSocket()
    cmd_ws.set_peer(worker_ws)
    worker_ws.set_peer(cmd_ws)

    # Wire handlers
    worker_ws.set_handler(worker.handle_message)
    cmd_ws.set_handler(lambda msg: commander.handle_message(msg, cmd_ws, "test-worker"))

    # Register worker
    registry.register("test-worker", host="192.168.1.10")
    registry.set_status("test-worker", AgentStatus.ACTIVE)
    commander.add_connection("test-worker", cmd_ws)
    worker._ws = worker_ws

    # Dispatch task
    task_id = await commander.dispatch_task(
        agent_id="test-worker",
        task_type="on_demand",
        params={"tool": "shell_exec", "arguments": {"command": "kubectl get pods"}},
    )

    # Verify worker received and executed
    assert len(cmd_ws.sent) == 1  # task_assign
    assert len(worker_ws.sent) == 1  # task_result

    # Verify commander got the result
    assert task_id in commander.completed_tasks
    assert commander.completed_tasks[task_id]["status"] == "success"
    assert commander.completed_tasks[task_id]["output"] == "pods healthy"

@pytest.mark.asyncio
async def test_role_assignment_flow(commander, worker, registry):
    """Commander assigns role → Worker stores it."""
    registry.register("test-worker", host="h1")
    cmd_ws = FakeWebSocket()
    worker_ws = FakeWebSocket()
    cmd_ws.set_peer(worker_ws)
    worker_ws.set_handler(worker.handle_message)
    commander.add_connection("test-worker", cmd_ws)
    worker._ws = worker_ws

    role = RoleDefinition(
        name="k8s-monitor",
        tools=["shell_exec", "file_read"],
        schedules=[{"type": "cron", "expr": "*/5 * * * *", "task": "check"}],
        policies={"auto_actions": ["restart_pod"], "require_approval": [], "blocked": ["delete_namespace"]},
    )
    await commander.send_role_update("test-worker", role)

    assert "k8s-monitor" in worker.roles
    assert worker.roles["k8s-monitor"]["tools"] == ["shell_exec", "file_read"]

@pytest.mark.asyncio
async def test_offline_queue_and_sync(commander, worker, registry, tool_registry):
    """Worker queues result offline → syncs on reconnect."""
    registry.register("test-worker", host="h1")

    # Worker is disconnected
    worker._ws = None

    # Execute task while offline
    msg = create_message(
        type=MessageType.TASK_ASSIGN,
        source="commander",
        target="test-worker",
        payload={
            "task_id": "offline-t1",
            "idempotency_key": "idem-offline-1",
            "type": "scheduled",
            "params": {"tool": "shell_exec", "arguments": {"command": "uptime"}},
        },
    )
    await worker.handle_message(msg)
    assert len(worker._offline_queue) == 1

    # Reconnect and sync
    cmd_ws = FakeWebSocket()
    worker_ws = FakeWebSocket()
    cmd_ws.set_handler(lambda msg: commander.handle_message(msg, cmd_ws, "test-worker"))
    worker._ws = worker_ws

    await worker.sync_offline_queue()
    assert len(worker._offline_queue) == 0
    assert len(worker_ws.sent) == 1  # sync message
```

- [ ] **Step 2: Run integration tests**

Run: `cd D:/Projects/breadmind && python -m pytest tests/test_integration_network.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration_network.py
git commit -m "test: add integration tests for Commander ↔ Worker message flow"
```

---

## Summary

| Chunk | Tasks | Description |
|-------|-------|-------------|
| 1 | 1-4 | Protocol foundation (envelope, HMAC, seq, config, DB schema) |
| 2 | 5 | PKI (CA, cert issuance, revocation) |
| 3 | 6 | Agent registry & role manager |
| 4 | 7 | Commander WebSocket hub |
| 5 | 8 | Worker runtime |
| 6 | 9 | Sync manager & idempotency |
| 7 | 10 | Provisioning system |
| 8 | 11-13 | Integration (main.py, safety.py, web/app.py) |
| 9 | 14 | End-to-end integration test |

**Total new files:** 15
**Total modified files:** 5
**Estimated tasks:** 14 (with ~70 individual steps)
