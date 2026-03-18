# tests/test_pki.py
import pytest
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
