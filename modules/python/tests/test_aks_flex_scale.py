#!/usr/bin/env python3
"""Unit tests for deterministic AKS Flex scale helpers."""

import base64
import unittest
from unittest.mock import patch

from aks_flex_scale import csr
from aks_flex_scale.config import DEFAULTS, node_names, required_prefix, validate_config
from aks_flex_scale.orchestrator import _percentile, action_allowed


def valid_config():
    return {**DEFAULTS, "subscriptionId": "00000000-0000-0000-0000-000000000001",
            "flexVmSize": "Standard_D4s_v5"}


class ConfigTest(unittest.TestCase):
    def test_default_scale_capacity(self):
        validate_config(valid_config())
        self.assertEqual(required_prefix(1000, 110), 15)

    def test_small_subnet_is_rejected(self):
        config = valid_config()
        config["flexSubnetCidr"] = "10.65.0.0/24"
        with self.assertRaisesRegex(ValueError, "headroom"):
            validate_config(config)

    def test_small_pod_cidr_is_rejected(self):
        config = valid_config()
        config["flexPodCidr"] = "10.68.0.0/16"
        with self.assertRaisesRegex(ValueError, "addresses"):
            validate_config(config)

    def test_names_are_deterministic(self):
        config = valid_config()
        config["nodeCount"] = 3
        self.assertEqual(node_names(config), ["flex-scale-0000", "flex-scale-0001", "flex-scale-0002"])

    def test_timeout_above_one_hour_is_rejected(self):
        config = valid_config()
        config["joinTimeoutSeconds"] = 3601
        with self.assertRaisesRegex(ValueError, "one-hour"):
            validate_config(config)

    def test_static_website_container_is_rejected(self):
        config = valid_config()
        config["gateContainer"] = "$web"
        with self.assertRaisesRegex(ValueError, "forbidden"):
            validate_config(config)

    def test_bootstrap_modes(self):
        for mode in ("local-config", "rp"):
            config = valid_config()
            config["bootstrapMode"] = mode
            validate_config(config)
        config = valid_config()
        config["bootstrapMode"] = "unsupported"
        with self.assertRaisesRegex(ValueError, "bootstrapMode"):
            validate_config(config)


class CsrTest(unittest.TestCase):
    @patch.object(csr, "csr_subject", return_value=("system:node:flex-scale-0001",
                                                    ["system:nodes", "aks-flex-node-daemons"]))
    def test_exact_daemon_identity(self, _):
        value = {"spec": {"signerName": csr.CLIENT_SIGNER, "username": "system:bootstrap:abc",
                          "groups": [csr.BOOTSTRAP_GROUP], "request": "unused"}}
        node, daemon, _ = csr.exact_identity(value, {"flex-scale-0001"})
        self.assertEqual(node, "flex-scale-0001")
        self.assertTrue(daemon)

    @patch.object(csr, "csr_subject", return_value=("system:node:other", ["system:nodes"]))
    def test_non_allowlisted_node_is_rejected(self, _):
        value = {"spec": {"signerName": csr.CLIENT_SIGNER, "username": "system:bootstrap:abc",
                          "groups": [csr.BOOTSTRAP_GROUP], "request": "unused"}}
        node, _, _ = csr.exact_identity(value, {"flex-scale-0001"})
        self.assertIsNone(node)

    def test_invalid_request_is_safe(self):
        self.assertEqual(csr.csr_subject(base64.b64encode(b"not a csr").decode()), (None, []))


class PermissionTest(unittest.TestCase):
    def test_permission_entries_are_a_union(self):
        entries = [
            {"actions": ["*"], "notActions": ["Microsoft.Authorization/*/Write"]},
            {"actions": ["Microsoft.Authorization/roleAssignments/write"], "notActions": []},
        ]
        self.assertTrue(action_allowed(entries, "Microsoft.Authorization/roleAssignments/write"))

    def test_entry_local_exclusion_blocks(self):
        entries = [{"actions": ["*"], "notActions": ["Microsoft.Authorization/*/Write"]}]
        self.assertFalse(action_allowed(entries, "Microsoft.Authorization/roleAssignments/write"))


class MetricsTest(unittest.TestCase):
    def test_nearest_rank_percentile(self):
        self.assertEqual(_percentile([1, 2, 3, 4], 50), 2)
        self.assertEqual(_percentile([1, 2, 3, 4], 99), 4)


if __name__ == "__main__":
    unittest.main()
