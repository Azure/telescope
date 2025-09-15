import sys
import unittest
import argparse
from unittest.mock import patch

from clusterloader2.large_cluster.large_cluster import (
    LargeClusterArgsParser,
    LargeClusterRunner,
    LargeCluster,
)


class TestLargeClusterArgsParser(unittest.TestCase):

    def _get_arg_dests(self, parser: argparse.ArgumentParser):
        return {a.dest for a in parser._actions}  # pylint: disable=protected-access

    def test_add_configure_args(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        configure_parser = sub.add_parser("configure")
        LargeClusterArgsParser().add_configure_args(configure_parser)

        dests = self._get_arg_dests(configure_parser)
        expected = {
            "cpu_per_node",
            "node_count",
            "node_per_step",
            "repeats",
            "operation_timeout",
            "provider",
            "cilium_enabled",
            "scrape_containerd",
            "cl2_override_file",
        }
        self.assertTrue(expected.issubset(dests))

    def test_add_validate_args(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        validate_parser = sub.add_parser("validate")
        LargeClusterArgsParser().add_validate_args(validate_parser)

        dests = self._get_arg_dests(validate_parser)
        expected = {"node_count", "operation_timeout"}
        self.assertTrue(expected.issubset(dests))

    def test_add_execute_args(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        execute_parser = sub.add_parser("execute")
        LargeClusterArgsParser().add_execute_args(execute_parser)

        dests = self._get_arg_dests(execute_parser)
        expected = {
            "cl2_image",
            "cl2_config_dir",
            "cl2_report_dir",
            "cl2_config_file",
            "kubeconfig",
            "provider",
            "scrape_containerd",
        }
        self.assertTrue(expected.issubset(dests))

    def test_add_collect_args(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        collect_parser = sub.add_parser("collect")
        LargeClusterArgsParser().add_collect_args(collect_parser)

        dests = self._get_arg_dests(collect_parser)
        expected = {
            "cpu_per_node",
            "node_count",
            "repeats",
            "cl2_report_dir",
            "cloud_info",
            "run_id",
            "run_url",
            "result_file",
        }
        self.assertTrue(expected.issubset(dests))

    def test_parse_configure_command_end_to_end(self):
        # Simulate full CLI invocation for configure
        argv = [
            "prog",
            "configure",
            "8",            # cpu_per_node
            "1000",         # node_count
            "100",          # node_per_step
            "3",            # repeats
            "30m",          # operation_timeout
            "azure",        # provider
            "True",         # cilium_enabled
            "False",        # scrape_containerd
            "/tmp/overrides.yaml",  # cl2_override_file
        ]
        with patch.object(sys, "argv", argv):
            lc = LargeCluster()
            args = lc.parse_arguments()

        self.assertEqual(args.command, "configure")
        self.assertEqual(args.cpu_per_node, 8)
        self.assertEqual(args.node_count, 1000)
        self.assertEqual(args.node_per_step, 100)
        self.assertEqual(args.repeats, 3)
        self.assertEqual(args.operation_timeout, "30m")
        self.assertEqual(args.provider, "azure")
        self.assertTrue(args.cilium_enabled)
        self.assertFalse(args.scrape_containerd)
        self.assertEqual(args.cl2_override_file, "/tmp/overrides.yaml")


class TestLargeClusterRunner(unittest.TestCase):
    def setUp(self):
        self.runner = LargeClusterRunner()

    @patch("clusterloader2.large_cluster.large_cluster.calculate_config",
           return_value=(100, 50, 40, 250))
    def test_configure_basic(self, mock_calc):
        config = self.runner.configure(
            cpu_per_node=8,
            node_count=1000,
            node_per_step=100,
            repeats=3,
            operation_timeout="30m",
            provider="azure",
            cilium_enabled=False,
            scrape_containerd=False,
        )
        # calculate_config called with cpu_per_node and node_per_step (per implementation)
        mock_calc.assert_called_once_with(8, 100, "azure")

        expected_keys = {
            "CL2_NODES",
            "CL2_LOAD_TEST_THROUGHPUT",
            "CL2_NODES_PER_NAMESPACE",
            "CL2_NODES_PER_STEP",
            "CL2_PODS_PER_NODE",
            "CL2_DEPLOYMENT_SIZE",
            "CL2_LATENCY_POD_CPU",
            "CL2_REPEATS",
            "CL2_STEPS",
            "CL2_OPERATION_TIMEOUT",
            "CL2_PROMETHEUS_TOLERATE_MASTER",
            "CL2_PROMETHEUS_MEMORY_LIMIT_FACTOR",
            "CL2_PROMETHEUS_MEMORY_SCALE_FACTOR",
            "CL2_PROMETHEUS_CPU_SCALE_FACTOR",
            "CL2_PROMETHEUS_NODE_SELECTOR",
            "CL2_POD_STARTUP_LATENCY_THRESHOLD",
        }
        self.assertTrue(expected_keys.issubset(config.keys()))
        self.assertEqual(config["CL2_NODES"], 1000)
        self.assertEqual(config["CL2_STEPS"], 1000 // 100)
        self.assertEqual(config["CL2_REPEATS"], 3)
        self.assertEqual(config["CL2_OPERATION_TIMEOUT"], "30m")
        # Values from patched calculate_config
        self.assertEqual(config["CL2_LOAD_TEST_THROUGHPUT"], 100)
        self.assertEqual(config["CL2_NODES_PER_NAMESPACE"], 50)
        self.assertEqual(config["CL2_PODS_PER_NODE"], 40)
        self.assertEqual(config["CL2_DEPLOYMENT_SIZE"], 40)
        self.assertEqual(config["CL2_LATENCY_POD_CPU"], 250)
        # No cilium/containerd keys
        self.assertNotIn("CL2_CILIUM_METRICS_ENABLED", config)
        self.assertNotIn("CL2_SCRAPE_CONTAINERD", config)

    @patch("clusterloader2.large_cluster.large_cluster.calculate_config",
           return_value=(200, 60, 30, 111))
    def test_configure_with_cilium_and_containerd(self, _mock_calc):
        config = self.runner.configure(
            cpu_per_node=16,
            node_count=900,
            node_per_step=90,
            repeats=2,
            operation_timeout="45m",
            provider="aws",
            cilium_enabled=True,
            scrape_containerd=True,
        )
        self.assertIn("CL2_CILIUM_METRICS_ENABLED", config)
        self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR", config)
        self.assertIn("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT", config)
        self.assertIn("CL2_SCRAPE_CONTAINERD", config)
        self.assertEqual(config["CONTAINERD_SCRAPE_INTERVAL"], "5m")
        self.assertEqual(config["CL2_SCRAPE_CONTAINERD"], "true")

    @patch("clusterloader2.large_cluster.large_cluster.KubernetesClient.wait_for_nodes_ready")
    def test_validate_calls_wait_for_nodes_ready(self, mock_wait):
        self.runner.validate(node_count=50, operation_timeout=15)
        mock_wait.assert_called_once_with(
            node_count=50,
            operation_timeout_in_minutes=15,
        )

    @patch("clusterloader2.large_cluster.base.ClusterLoader2Base.Runner.execute")
    def test_execute_passes_overrides_and_prometheus(self, mock_exec):
        self.runner.execute(
            kubeconfig="/path/kubeconfig",
            cl2_image="image:tag",
            cl2_config_dir="/cfg",
            cl2_report_dir="/rep",
            provider="azure",
            cl2_config_file="custom.yaml",
            scrape_containerd=True,
        )
        # Ensure super().execute invoked with injected flags
        self.assertTrue(mock_exec.called)
        kwargs = mock_exec.call_args.kwargs
        self.assertEqual(kwargs["kubeconfig"], "/path/kubeconfig")
        self.assertEqual(kwargs["cl2_image"], "image:tag")
        self.assertEqual(kwargs["cl2_config_dir"], "/cfg")
        self.assertEqual(kwargs["cl2_report_dir"], "/rep")
        self.assertEqual(kwargs["provider"], "azure")
        self.assertEqual(kwargs["cl2_config_file"], "custom.yaml")
        self.assertTrue(kwargs["overrides"])
        self.assertTrue(kwargs["enable_prometheus"])
        self.assertTrue(kwargs["scrape_containerd"])

    @patch("clusterloader2.large_cluster.large_cluster.calculate_config",
           return_value=(123, 10, 25, 77))
    @patch("clusterloader2.large_cluster.large_cluster.datetime")
    @patch("clusterloader2.large_cluster.large_cluster.LargeClusterRunner.process_cl2_reports",
           return_value="PROCESSED_CONTENT")
    def test_collect_builds_template_and_calls_process(
        self,
        mock_process,
        mock_datetime,
        _mock_calc,
    ):
        fixed_dt = unittest.mock.MagicMock()
        fixed_dt.strftime.return_value = "2025-01-01T00:00:00Z"
        mock_datetime.now.return_value = fixed_dt
        mock_datetime.timezone = sys.modules.get("datetime").timezone  # pass through if needed
        mock_datetime.utcnow = None

        result = self.runner.collect(
            test_status="success",
            cpu_per_node=4,
            node_count=80,
            repeats=5,
            cl2_report_dir="/reports",
            cloud_info='{"cloud":"azure"}',
            run_id="RID123",
            run_url="http://run",
        )
        self.assertEqual(result, "PROCESSED_CONTENT")
        mock_process.assert_called_once()
        called_dir, template = mock_process.call_args.args
        self.assertEqual(called_dir, "/reports")
        # Template fields
        self.assertEqual(template["status"], "success")
        self.assertEqual(template["cpu_per_node"], 4)
        self.assertEqual(template["node_count"], 80)
        # pods_per_node (25) * node_count
        self.assertEqual(template["pod_count"], 80 * 25)
        self.assertEqual(template["churn_rate"], 5)
        self.assertEqual(template["cloud_info"], '{"cloud":"azure"}')
        self.assertEqual(template["run_id"], "RID123")
        self.assertEqual(template["run_url"], "http://run")
        self.assertIsNone(template["group"])
        self.assertIsNone(template["measurement"])
        self.assertIsNone(template["result"])
        self.assertEqual(template["timestamp"], "2025-01-01T00:00:00Z")

if __name__ == "__main__":
    unittest.main()
