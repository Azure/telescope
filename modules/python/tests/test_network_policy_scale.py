import os
import unittest
import tempfile
import json
from clusterloader2.slo.network_policy_scale import (
    configure_clusterloader2,
    collect_clusterloader2,
)


class TestConfigureNetworkPolicyScale(unittest.TestCase):
    def test_default_config(self):
        # Create a temporary file for the override file
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name

        try:
            # Call function with basic parameters and both cilium flags off.
            configure_clusterloader2(
                number_of_groups=2,
                clients_per_group=3,
                servers_per_group=4,
                workers_per_client=5,
                netpol_type="k8s",
                test_duration_secs=10,
                cilium_enabled=False,
                cilium_envoy_enabled=False,
                l7_enabled=False,
                repeats=0,
                netpol_test="soak",
                restart_deletion_enabled=False,
                l3_l4_port_enabled=False,
                override_file=tmp_path,
            )

            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Assert that the basic test config lines appear
            self.assertIn("CL2_DURATION: 10s", content)
            self.assertIn("CL2_NUMBER_OF_CLIENTS_PER_GROUP: 3", content)
            self.assertIn("CL2_NETWORK_POLICY_TYPE: k8s", content)
            self.assertIn("CL2_SOAK_TEST: true", content)
            # Assert that Cilium config sections are not present
            self.assertNotIn("CL2_CILIUM_ENABLED: true", content)
            self.assertNotIn("CL2_CILIUM_ENVOY_ENABLED: true", content)
            self.assertNotIn("CL2_NET_POLICY_L7_ENABLED: true", content)
            self.assertNotIn("CL2_REPEATS: 1", content)
            self.assertNotIn("CL2_ENABLE_NETWORK_POLICY_ENFORCEMENT_LATENCY_TEST: true", content)
            self.assertNotIn("CL2_RESTART_DELETION_ENABLED: true", content)
        finally:
            os.remove(tmp_path)

    def test_with_cilium_configs_l7(self):
        # Create a temporary file for the override file
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name

        try:
            # Call function with Cilium-related flags enabled.
            configure_clusterloader2(
                number_of_groups=1,
                clients_per_group=2,
                servers_per_group=3,
                workers_per_client=4,
                netpol_type="cnp",
                test_duration_secs=20,
                cilium_enabled=True,
                cilium_envoy_enabled=True,
                l7_enabled=True,
                repeats=0,
                netpol_test="soak",
                restart_deletion_enabled=False,
                l3_l4_port_enabled=False,
                override_file=tmp_path,
            )

            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Assert that test config lines appear
            self.assertIn("CL2_DURATION: 20s", content)
            self.assertIn("CL2_NUMBER_OF_GROUPS: 1", content)
            self.assertIn("CL2_NETWORK_POLICY_TYPE: cnp", content)
            # Assert that Cilium config sections are present
            self.assertIn("CL2_CILIUM_ENABLED: true", content)
            self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true", content)
            self.assertIn("CL2_CILIUM_ENVOY_ENABLED: true", content)
            self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_ENVOY: true", content)
            self.assertIn("CL2_NET_POLICY_L7_ENABLED: true", content)
            self.assertIn("CL2_REPEATS: 0", content)
            self.assertIn("CL2_SOAK_TEST: true", content)
            self.assertNotIn("CL2_ENABLE_NETWORK_POLICY_ENFORCEMENT_LATENCY_TEST: true", content)
            self.assertNotIn("CL2_RESTART_DELETION_ENABLED: true", content)
        finally:
            os.remove(tmp_path)

    def test_with_cilium_configs_l3_l4(self):
        # Create a temporary file for the override file
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name

        try:
            # Call function with Cilium-related flags enabled.
            configure_clusterloader2(
                number_of_groups=1,
                clients_per_group=2,
                servers_per_group=3,
                workers_per_client=4,
                netpol_type="cnp",
                test_duration_secs=20,
                cilium_enabled=True,
                cilium_envoy_enabled=False,
                l7_enabled=False,
                repeats=2,
                netpol_test="soak",
                restart_deletion_enabled=True,
                l3_l4_port_enabled=True,
                override_file=tmp_path,
            )

            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Assert that test config lines appear
            self.assertIn("CL2_DURATION: 20s", content)
            self.assertIn("CL2_NUMBER_OF_GROUPS: 1", content)
            self.assertIn("CL2_NETWORK_POLICY_TYPE: cnp", content)
            # Assert that Cilium config sections are present
            self.assertIn("CL2_CILIUM_ENABLED: true", content)
            self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true", content)
            self.assertIn("CL2_REPEATS: 2", content)
            self.assertIn("CL2_SOAK_TEST: true", content)
            self.assertIn("CL2_RESTART_DELETION_ENABLED: true", content)
            self.assertIn("CL2_NET_POLICY_L3_L4_ENABLED: true", content)
            self.assertNotIn("CL2_CILIUM_ENVOY_ENABLED: true", content)
            self.assertNotIn("CL2_NET_POLICY_L7_ENABLED: true", content)
            self.assertNotIn("CL2_CILIUM_ENVOY_ENABLED: true", content)
            self.assertNotIn("CL2_ENABLE_NETWORK_POLICY_ENFORCEMENT_LATENCY_TEST: true", content)
        finally:
            os.remove(tmp_path)


class TestNetworkPolicyScale(unittest.TestCase):
    def test_collect_clusterloader2(self):
        # Setup using provided mock report directory
        # set report_dir path to ./mock_data/network-policy-scale/report
        cl2_report_dir = os.path.join(
            os.path.dirname(__file__), "mock_data", "network-policy-scale", "report"
        )
        # Create a temporary file for result output
        result_file = tempfile.mktemp()
        # Setup additional parameters
        node_count = 5
        pod_count = 10
        cloud_info = json.dumps({"cloud": "test_cloud"})
        run_id = "run123"
        run_url = "http://example.com/run123"
        test_type = "unit-test"

        # Call the function under test
        collect_clusterloader2(
            node_count,
            pod_count,
            cl2_report_dir,
            cloud_info,
            run_id,
            run_url,
            result_file,
            test_type,
        )
        # Verify that the result file is created and contains expected data
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertTrue(len(content) > 0)
        # TODO: Add more specific assertions based on expected content


if __name__ == "__main__":
    unittest.main()
