import sys
import unittest
import argparse
from unittest.mock import patch

from clusterloader2.large_cluster.large_cluster import (
    LargeClusterArgsParser,
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


if __name__ == "__main__":
    unittest.main()
