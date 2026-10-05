"""Kubernetes resource quantity parsing."""

import re

_QTY = re.compile(r"^([0-9.]+)([a-zA-Z]*)$")
_MEM_UNITS = {"": 1, "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4,
              "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4}


def parse_cpu(q: str | None) -> float:
    """'250m' -> 0.25, '2' -> 2.0, '' -> 0.0"""
    if not q:
        return 0.0
    if q.endswith("m"):
        return float(q[:-1]) / 1000.0
    if q.endswith("n"):
        return float(q[:-1]) / 1e9
    if q.endswith("u"):
        return float(q[:-1]) / 1e6
    return float(q)


def parse_mem(q: str | None) -> int:
    """'256Mi' -> bytes"""
    if not q:
        return 0
    m = _QTY.match(q)
    if not m:
        return 0
    return int(float(m.group(1)) * _MEM_UNITS.get(m.group(2), 1))
