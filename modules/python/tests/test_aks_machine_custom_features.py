#!/usr/bin/env python3
"""Unit tests for AKS Machine API custom feature helpers."""
import unittest

from clients.aks_machine_custom_features import (
    custom_feature_headers,
    scriptless_enabled_value,
)


class TestAKSMachineCustomFeatures(unittest.TestCase):
    """Tests for custom feature header and metadata helpers."""

    def test_scriptless_enabled_value_from_custom_features(self):
        """DisableSelfContainedVHD marks the run as not scriptless-enabled."""
        self.assertEqual(scriptless_enabled_value(None), "yes")
        self.assertEqual(scriptless_enabled_value(""), "yes")
        self.assertEqual(scriptless_enabled_value("SomeOtherFeature"), "yes")
        self.assertEqual(
            scriptless_enabled_value("SomeOtherFeature, DisableSelfContainedVHD"),
            "no",
        )
        self.assertEqual(
            scriptless_enabled_value("SomeOtherFeature DisableSelfContainedVHD"),
            "yes",
        )
        self.assertEqual(
            scriptless_enabled_value("SomeOtherFeature;DisableSelfContainedVHD"),
            "yes",
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


if __name__ == "__main__":
    unittest.main()
