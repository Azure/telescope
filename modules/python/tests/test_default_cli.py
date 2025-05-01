import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from clusterloader2.default.cli import (
    collect_clusterloader2,
    configure_clusterloader2,
    validate_clusterloader2,
)


class TestConfigureClusterLoader2(unittest.TestCase):
    def test_configure_clusterloader2(self):
        # Create a temporary file for the override file
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name

        try:
            # Call the function with test data
            configure_clusterloader2(
                cpu_per_node=2,
                node_count=100,
                node_per_step=10,
                max_pods=40,
                repeats=1,
                operation_timeout="15m",
                provider="azure",
                cilium_enabled=False,
                scrape_containerd=False,
                service_test=True,
                cnp_test=False,
                ccnp_test=False,
                num_cnps=0,
                num_ccnps=0,
                dualstack=False,
                cl2_override_file=tmp_path,
                workload_type="job",
                job_count=1000,
                job_parallelism=1,
                job_completions=1,
                job_throughput=1000,
            )

            # Verify the content of the override file
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Assert each key-value pair
            self.assertIn("CL2_NODES: 100", content)
            self.assertIn("CL2_NODES_PER_STEP: 10", content)
            self.assertIn("CL2_OPERATION_TIMEOUT: 15m", content)
            self.assertIn("CL2_REPEATS: 1", content)
            self.assertIn("CL2_STEPS: 10", content)
            self.assertIn("CL2_JOBS: 1000", content)
            self.assertIn("CL2_JOB_PARALLELISM: 1", content)
            self.assertIn("CL2_JOB_COMPLETIONS: 1", content)
            self.assertIn("CL2_LOAD_TEST_THROUGHPUT: 1000", content)
            self.assertIn("CL2_SERVICE_TEST: true", content)
        finally:
            os.remove(tmp_path)


class TestValidateClusterLoader2(unittest.TestCase):

    @patch("clients.kubernetes_client.config.load_kube_config")
    @patch("clients.kubernetes_client.KubernetesClient.get_ready_nodes")
    def test_validate_clusterloader2_timeout(
        self, mock_get_ready_nodes, mock_load_kube_config
    ):

        # kubeconfig is not needed for this test but it has to be loaded to run KubernetesClient
        mock_load_kube_config.return_value = None
        # Mock the KubernetesClient and its get_ready_nodes method
        mock_get_ready_nodes.return_value = ["node1"]  # Only 1 node ready

        # Call the function and expect an exception due to timeout
        with self.assertRaises(Exception) as context:
            validate_clusterloader2(node_count=2, operation_timeout_in_minutes=1)

        # Verify the exception message
        self.assertIn(
            "Only 1 nodes are ready, expected 2 nodes!", str(context.exception)
        )

    @patch("clients.kubernetes_client.config.load_kube_config")
    @patch("clients.kubernetes_client.KubernetesClient.get_ready_nodes")
    def test_validate_clusterloader2_success(
        self, mock_get_ready_nodes, mock_load_kube_config
    ):
        mock_load_kube_config.return_value = None
        # Mock the KubernetesClient and its get_ready_nodes method
        mock_get_ready_nodes.side_effect = [
            ["node1"],  # First call: 1 node ready
            ["node1", "node2"],  # Second call: 2 nodes ready
        ]

        # Call the function with test data
        try:
            validate_clusterloader2(node_count=2, operation_timeout_in_minutes=1)
        except Exception as e:
            self.fail(f"validate_clusterloader2 raised an exception unexpectedly: {e}")

        # Verify that get_ready_nodes was at least 2 calls
        # The first call should return 1 node, and the second call should return 2 nodes
        self.assertGreaterEqual(mock_get_ready_nodes.call_count, 2)


class TestCollectClusterLoader2(unittest.TestCase):
    def test_collect_clusterloader2(self):
        # Create a temporary directory for the report
        cl2_report_dir = os.path.join(
            os.path.dirname(__file__), "mock_data", "default", "report"
        )
        # Create a temporary file for result output
        result_file = tempfile.mktemp()

        try:
            # Call the function with test data
            collect_clusterloader2(
                cpu_per_node=2,
                node_count=100,
                max_pods=40,
                repeats=1,
                cl2_report_dir=cl2_report_dir,
                cloud_info=json.dumps({"cloud": "aws"}),
                run_id="run123",
                run_url="http://example.com/run123",
                service_test=True,
                cnp_test=False,
                ccnp_test=False,
                result_file=result_file,
                test_type="unit-test",
                start_timestamp=None,
                workload_type="pod",
                job_count=None,
                job_parallelism=None,
                job_completions=None,
                job_throughput=None,
            )

            # Verify the content of the result file
            if os.path.exists(result_file):
                with open(result_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # Parse the content as JSON
                result_data = json.loads(content)

                # Assert each key-value pair
                self.assertEqual(result_data["node_count"], 100)
                self.assertEqual(result_data["churn_rate"], 1)
                self.assertEqual(result_data["status"], "success")
                self.assertEqual(result_data["group"], "job-scheduling")
                self.assertEqual(
                    result_data["measurement"],
                    "JobLifecycleLatency_JobLifecycleLatency",
                )

                # Assert nested result data
                self.assertEqual(result_data["result"]["data"]["Perc50"], 78000)
                self.assertEqual(result_data["result"]["data"]["Perc90"], 141000)
                self.assertEqual(result_data["result"]["data"]["Perc99"], 155000)
                self.assertEqual(result_data["result"]["unit"], "ms")
                self.assertEqual(
                    result_data["result"]["labels"]["Metric"], "create_to_start"
                )

                # Assert other fields
                self.assertEqual(result_data["cloud_info"], '{"cloud": "aws"}')
                self.assertEqual(result_data["run_id"], "run123")
                self.assertEqual(result_data["run_url"], "http://example.com/run123")
                self.assertEqual(result_data["test_type"], "unit-test")
                self.assertEqual(result_data["cpu_per_node"], 2)
                self.assertEqual(result_data["pod_count"], 4000)
            else:
                self.fail("Result file does not exist or is empty.")
        finally:
            if os.path.exists(result_file):
                os.remove(result_file)


if __name__ == "__main__":
    unittest.main()
