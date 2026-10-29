"""Verify regional VM eligibility and available vCPU quota before provisioning."""

import json
import sys
from pathlib import Path


def verify(skus, usage):
    required = {"cores": 30}
    for name, cpus in (("Standard_D2_v4", 6), ("Standard_D8s_v5", 24)):
        matches = [sku for sku in skus if sku["name"] == name]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one regional SKU record for {name}")
        sku = matches[0]
        if any(restriction["type"] == "Location" for restriction in sku["restrictions"]):
            raise ValueError(f"SKU {name} has a location restriction: {sku['restrictions']}")
        family = sku["family"].lower()
        required[family] = required.get(family, 0) + cpus
    quotas = {entry["name"]["value"].lower(): entry for entry in usage}
    for name, count in required.items():
        if name not in quotas:
            raise ValueError(f"Missing quota information: {name}")
        quota = quotas[name]
        available = quota["limit"] - quota["currentValue"]
        if available < count:
            raise ValueError(f"Insufficient {name} quota: need {count}, available {available}")


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    verify(
        json.loads((directory / "vm-skus.json").read_text()),
        json.loads((directory / "vm-usage.json").read_text()),
    )
    print("Regional VM eligibility and vCPU quota checks passed.")
