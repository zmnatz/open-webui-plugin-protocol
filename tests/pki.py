"""Throwaway certificates for the TLS tests, made with the openssl command."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# What Python's strict verification (3.13 and later) asks of each.
CA = "basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n"
LEAF = "basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
IDS = "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n"
LEAVES = {
    "server": "extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1\n",
    "client": "extendedKeyUsage=clientAuth\n",
}


def make_pki(folder: Path) -> Path:
    """A private CA (ca.pem) and what it signed: a certificate and key for a server on
    127.0.0.1 (server.pem, server.key) and for a client (client.pem, client.key)."""
    if not shutil.which("openssl"):
        pytest.skip("needs the openssl command")
    folder.mkdir(parents=True)

    def openssl(*args: str) -> None:
        subprocess.run(["openssl", *args], cwd=folder, check=True, capture_output=True)

    def request(name: str) -> None:
        openssl(
            "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-subj", f"/CN=owpp test {name}", "-keyout", f"{name}.key", "-out", f"{name}.csr",
        )  # fmt: skip

    def sign(name: str, extensions: str, *by: str) -> None:
        (folder / f"{name}.ext").write_text(extensions)
        openssl(
            "x509", "-req", "-days", "2", "-in", f"{name}.csr", "-out", f"{name}.pem",
            "-extfile", f"{name}.ext", *by,
        )  # fmt: skip

    request("ca")
    sign("ca", CA + "subjectKeyIdentifier=hash\n", "-signkey", "ca.key")
    for name, extensions in LEAVES.items():
        request(name)
        sign(name, LEAF + IDS + extensions, "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial")
    return folder
