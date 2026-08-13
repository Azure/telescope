"""Strict, exact-name CSR validation and approval."""

from __future__ import annotations

import base64
import re
from typing import Any

from .commands import run

CLIENT_SIGNER = "kubernetes.io/kube-apiserver-client"
BOOTSTRAP_GROUP = "system:bootstrappers:aks-flex-node"


def parse_subject(subject: str) -> tuple[str | None, list[str]]:
    value = subject.strip().removeprefix("subject=")
    cn = re.search(r"(?:^|[,+])CN=([^,+]+)", value)
    organizations = re.findall(r"(?:^|[,+])O=([^,+]+)", value)
    return (cn.group(1) if cn else None), organizations


def csr_subject(request: str) -> tuple[str | None, list[str]]:
    try:
        decoded = base64.b64decode(request, validate=True)
    except (ValueError, TypeError):
        return None, []
    result = run(["openssl", "req", "-noout", "-subject", "-nameopt", "RFC2253"],
                 input_bytes=decoded, timeout=10, check=False)
    if result.returncode != 0:
        return None, []
    return parse_subject(result.stdout.decode("utf-8", "replace"))


def exact_identity(csr: dict[str, Any], allowed_nodes: set[str]) -> tuple[str | None, bool, str]:
    spec = csr.get("spec", {})
    if spec.get("signerName") != CLIENT_SIGNER:
        return None, False, "wrong signer"
    username = str(spec.get("username", ""))
    groups = {str(item) for item in spec.get("groups", [])}
    cn, organizations = csr_subject(str(spec.get("request", "")))
    prefix = "system:node:"
    node = cn[len(prefix):] if cn and cn.startswith(prefix) else None
    if node not in allowed_nodes:
        return None, False, "subject CN is not an allowed node"
    bootstrap = username.startswith("system:bootstrap:") and BOOTSTRAP_GROUP in groups
    authenticated = username == cn and "system:nodes" in groups
    if not (bootstrap or authenticated):
        return None, False, "unexpected requester identity"
    if "system:nodes" not in organizations:
        return None, False, "subject lacks system:nodes organization"
    daemon = "aks-flex-node-daemons" in organizations
    return node, daemon, "exact daemon CSR" if daemon else "exact kubelet CSR"
