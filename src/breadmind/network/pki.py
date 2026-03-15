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
