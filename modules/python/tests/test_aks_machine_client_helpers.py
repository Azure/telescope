#!/usr/bin/env python3
"""Unit tests for AKS Machine API client helpers."""
import unittest

from clients.aks_machine_client_helpers import (
    build_readiness_envelope,
    custom_feature_headers,
    is_scriptless_enabled,
    machine_failure_detail,
    machine_name_prefix,
)


class TestAKSMachineClientHelpers(unittest.TestCase):
    """Tests for stateless AKS Machine client helpers."""

    def test_build_readiness_envelope_marks_hit_percentiles(self):
        """Readiness envelope records targets and hit/missed percentiles."""
        envelope = build_readiness_envelope(
            targets={50: 2, 70: 3, 90: 4, 99: 5, 100: 5},
            readiness_times={50: 12.5, 70: 18.0},
        )
        self.assertEqual(envelope["P50"]["target_nodes"], 2)
        self.assertEqual(envelope["P50"]["elapsed_time_seconds"], 12.5)
        self.assertTrue(envelope["P50"]["success"])
        self.assertEqual(envelope["P100"]["target_nodes"], 5)
        self.assertIsNone(envelope["P100"]["elapsed_time_seconds"])
        self.assertFalse(envelope["P100"]["success"])

    def test_is_scriptless_enabled_from_custom_features(self):
        """DisableSelfContainedVHD marks the run as not scriptless-enabled."""
        self.assertTrue(is_scriptless_enabled(None))
        self.assertTrue(is_scriptless_enabled(""))
        self.assertTrue(is_scriptless_enabled("SomeOtherFeature"))
        self.assertFalse(
            is_scriptless_enabled("SomeOtherFeature, DisableSelfContainedVHD")
        )
        self.assertTrue(
            is_scriptless_enabled("SomeOtherFeature DisableSelfContainedVHD")
        )
        self.assertTrue(
            is_scriptless_enabled("SomeOtherFeature;DisableSelfContainedVHD")
        )

    def test_custom_feature_headers_pass_through_comma_delimited_list(self):
        """Custom feature header uses the caller-provided comma-delimited string."""
        self.assertEqual(custom_feature_headers(None), {})
        self.assertEqual(
            custom_feature_headers("SomeOtherFeature, DisableSelfContainedVHD"),
            {
                "AKSHTTPCustomFeatures": (
                    "SomeOtherFeature, DisableSelfContainedVHD"
                ),
            },
        )
        self.assertEqual(
            custom_feature_headers("  SomeOtherFeature, DisableSelfContainedVHD  "),
            {
                "AKSHTTPCustomFeatures": (
                    "SomeOtherFeature, DisableSelfContainedVHD"
                ),
            },
        )

    def test_machine_failure_detail_extracts_compact_error(self):
        """Machine failure details include a truncated error message."""
        detail = machine_failure_detail({
            "name": "scale2-machine-1",
            "properties": {
                "provisioningState": "Failed",
                "status": {
                    "provisioningError": {
                        "code": "FailedToCreateOrUpdateVirtualMachineExtension",
                        "message": "x" * 301,
                    }
                },
            },
        })
        self.assertEqual(detail["name"], "scale2-machine-1")
        self.assertEqual(detail["provisioningState"], "Failed")
        self.assertEqual(
            detail["error_code"], "FailedToCreateOrUpdateVirtualMachineExtension"
        )
        self.assertEqual(detail["error_message"], "x" * 300)

    def test_machine_name_prefix_small(self):
        """Counts < 1000 emit literal scale<N>."""
        self.assertEqual(machine_name_prefix(1), "scale1")
        self.assertEqual(machine_name_prefix(500), "scale500")

    def test_machine_name_prefix_thousand_multiples(self):
        """Multiples of 1000 collapse to scale<N>k for stable Kusto keys."""
        self.assertEqual(machine_name_prefix(1000), "scale1k")
        self.assertEqual(machine_name_prefix(2000), "scale2k")

    def test_machine_name_prefix_non_multiple_thousand(self):
        """Non-multiple-of-1000 counts >= 1000 stay literal."""
        self.assertEqual(machine_name_prefix(1500), "scale1500")


if __name__ == "__main__":
    unittest.main()
