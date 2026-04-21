"""Pure-Python TLS certificate generation for konnectivity mTLS."""

import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .config import log
from .utils import run


def _generate_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def generate_certs(cert_dir: Path, test_name: str, server_ip: str = "") -> Path:
    """Generate CA, server, and client TLS certs for konnectivity mTLS."""
    cert_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    validity = timedelta(days=365)

    # --- CA ---
    ca_key = _generate_key()
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"konnectivity-ca-{test_name}")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + validity)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(cert_dir / "ca.key", ca_key)
    _write_cert(cert_dir / "ca.crt", ca_cert)

    # --- Server cert ---
    server_key = _generate_key()
    san_dns = [
        x509.DNSName("konnectivity-server"),
        x509.DNSName(f"konnectivity-server.{test_name}.svc.cluster.local"),
        x509.DNSName(f"*.{test_name}.svc.cluster.local"),
        x509.DNSName("localhost"),
    ]
    san_ips = [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    if server_ip:
        san_ips.append(x509.IPAddress(ipaddress.ip_address(server_ip)))

    server_csr = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "konnectivity-server")]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + validity)
        .add_extension(x509.SubjectAlternativeName(san_dns + san_ips), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(cert_dir / "server.key", server_key)
    _write_cert(cert_dir / "server.crt", server_csr)

    # --- Client cert (for agent + vmagent-proxy) ---
    client_key = _generate_key()
    client_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "konnectivity-agent")]))
        .issuer_name(ca_name)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + validity)
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(cert_dir / "client.key", client_key)
    _write_cert(cert_dir / "client.crt", client_cert)

    log.info("Certs generated in %s (CA + server + client)", cert_dir)
    return cert_dir


def create_cert_secret(kubeconfig: str, namespace: str, cert_dir: Path) -> None:
    create_cmd = [
        "kubectl", "--kubeconfig", kubeconfig, "-n", namespace,
        "create", "secret", "generic", "konnectivity-certs",
        f"--from-file=ca.crt={cert_dir}/ca.crt",
        f"--from-file=server.crt={cert_dir}/server.crt",
        f"--from-file=server.key={cert_dir}/server.key",
        f"--from-file=client.crt={cert_dir}/client.crt",
        f"--from-file=client.key={cert_dir}/client.key",
        "--dry-run=client", "-o", "yaml",
    ]
    result = run(create_cmd)
    run(["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"],
        input=result.stdout, capture=False)
