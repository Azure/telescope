import unittest
import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, mock_open
from fio.fio import validate, execute, collect, main

class TestFio(unittest.TestCase):
    def setUp(self):
        self.mock_kubernetes_client = MagicMock()
        self.mock_logger = MagicMock()

    @patch("clients.kubernetes_client.KubernetesClient.wait_for_nodes_ready")
    def test_validate(self, mock_wait_for_nodes_ready):
        node_count = 3
        operation_timeout = 10
        validate(node_count, operation_timeout)
        mock_wait_for_nodes_ready.assert_called_once_with(node_count, operation_timeout)

    @patch("fio.fio.KUBERNETES_CLIENT")
    @patch("fio.fio.yaml.dump")
    @patch("fio.fio.os.makedirs")
    @patch("subprocess.run")
    @patch("builtins.open", new_callable=mock_open)
    def test_execute_success(
        self, mock_open_file, mock_run, mock_makedirs, mock_yaml_dump, mock_k8s_client
    ):
        # Test parameters
        block_size = "4k"
        iodepth = 16
        method = "read"
        runtime = 60
        numjobs = 1
        file_size = "10G"
        storage_name = "fio"
        kustomize_dir = "/tmp/kustomize"
        result_dir = "/tmp/results"

        # Mock the kubernetes client methods
        mock_pod = MagicMock()
        mock_pod.metadata.name = "fio-pod-12345"
        mock_k8s_client.wait_for_job_completed.return_value = "fio"
        mock_k8s_client.get_pods_by_namespace.return_value = [mock_pod]
        mock_k8s_client.get_pod_logs.return_value = '{"result": "success"}'

        # Mock subprocess.run to simulate command execution
        mock_run.return_value = MagicMock(returncode=0, stdout=b'{"result": "success"}')

        # Call the execute function
        execute(
            block_size,
            iodepth,
            method,
            runtime,
            numjobs,
            file_size,
            storage_name,
            kustomize_dir,
            result_dir,
        )

        # Verify the yaml patch was written
        mock_yaml_dump.assert_called_once()

        # Verify subprocess.run was called twice (create and delete)
        self.assertEqual(mock_run.call_count, 2)

        # Verify the create command
        create_call = mock_run.call_args_list[0]
        self.assertTrue("kustomize build" in create_call[0][0])
        self.assertTrue("kubectl apply" in create_call[0][0])

        # Verify the delete command
        delete_call = mock_run.call_args_list[1]
        self.assertTrue("kustomize build" in delete_call[0][0])
        self.assertTrue("kubectl delete" in delete_call[0][0])

        # Verify the result directory was created
        mock_makedirs.assert_called_once_with(result_dir, exist_ok=True)

        # Verify the Kubernetes client was used to wait for job completion
        mock_k8s_client.wait_for_job_completed.assert_called_once_with(
            job_name="fio",
            timeout=runtime + 300,
        )

        # Verify the pods were retrieved by namespace
        mock_k8s_client.get_pods_by_namespace.assert_called_once_with(
            namespace="default", label_selector="job-name=fio"
        )

        # Verify pod logs were retrieved
        mock_k8s_client.get_pod_logs.assert_called_once_with("fio-pod-12345")

        # Verify files were written (result file and metadata file)
        self.assertEqual(
            mock_open_file.call_count, 3
        )  # patch file + result file + metadata file

    @patch("fio.fio.KUBERNETES_CLIENT")
    @patch("fio.fio.yaml.dump")
    @patch("fio.fio.os.makedirs")
    @patch("subprocess.run")
    @patch("builtins.open", new_callable=mock_open)
    def test_execute_failure_with_no_pods(
        self, mock_open_file, mock_run, mock_makedirs, mock_yaml_dump, mock_k8s_client # pylint: disable=unused-argument
    ):
        # Test parameters
        block_size = "4k"
        iodepth = 16
        method = "read"
        runtime = 60
        numjobs = 1
        file_size = "10G"
        storage_name = "fio"
        kustomize_dir = "/tmp/kustomize"
        result_dir = "/tmp/results"

        # Mock subprocess.run to simulate command execution
        mock_run.return_value = MagicMock(returncode=0, stdout=b'{"result": "success"}')

        # Mock the kubernetes client methods to return no pods
        mock_k8s_client.wait_for_job_completed.return_value = "fio"
        mock_k8s_client.get_pods_by_namespace.return_value = []

        # Call the execute function and expect an exception
        with self.assertRaises(RuntimeError) as context:
            execute(
                block_size,
                iodepth,
                method,
                runtime,
                numjobs,
                file_size,
                storage_name,
                kustomize_dir,
                result_dir,
            )

        self.assertEqual(str(context.exception), "No pods found for the fio job.")

    @patch('builtins.open', new_callable=mock_open)
    @patch('fio.fio.datetime')
    @patch('fio.fio.logger')
    def test_collect_success(self, mock_logger, mock_datetime, mock_open_file):
        # Test parameters
        vm_size = "Standard_D8s_v3"
        block_size = "4k"
        iodepth = 16
        method = "read"
        numjobs = 1
        file_size = "10G"
        result_dir = "/tmp/results"
        run_url = "http://test.com/run"
        cloud_info = {"cloud": "azure"}

        # Mock current time
        mock_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        # Mock file data
        mock_raw_result = {
            "jobs": [{
                "read": {
                    "iops_mean": 100,
                    "bw_mean": 200,
                    "clat_ns": {
                        "mean": 300,
                        "percentile": {
                            "50.000000": 400,
                            "99.000000": 500,
                            "99.900000": 600
                        }
                    }
                },
                "write": {
                    "iops_mean": 700,
                    "bw_mean": 800,
                    "clat_ns": {
                        "mean": 900,
                        "percentile": {
                            "50.000000": 1000,
                            "99.000000": 1100,
                            "99.900000": 1200
                        }
                    }
                }
            }]
        }
        mock_metadata = {
            "block_size": block_size,
            "iodepth": iodepth,
            "method": method,
            "file_size": file_size,
            "runtime": 60,
            "numjobs": numjobs,
            "storage_name": "fio"
        }

        # Setup mock file reads
        mock_open_file.return_value.__enter__.return_value.read.side_effect = [
            json.dumps(mock_raw_result),
            json.dumps(mock_metadata)
        ]

        # Collect test
        collect(
            vm_size,
            block_size,
            iodepth,
            method,
            numjobs,
            file_size,
            result_dir,
            run_url,
            cloud_info,
        )

        # Verify file operations
        mock_open_file.assert_any_call(f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}.json", "r", encoding="utf-8")
        mock_open_file.assert_any_call(f"{result_dir}/fio-{block_size}-{iodepth}-{method}-{numjobs}-{file_size}-metadata.json", "r", encoding="utf-8")
        mock_open_file.assert_any_call(f"{result_dir}/results.json", "a", encoding="utf-8")

        # Verify written content
        expected_result = {
            'timestamp': mock_now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'vm_size': vm_size,
            'cloud_info': cloud_info,
            'read_iops_avg': 100,
            'read_bw_avg': 200,
            'read_lat_avg': 300,
            'write_iops_avg': 700,
            'write_bw_avg': 800,
            'write_lat_avg': 900,
            'read_lat_p50': 400,
            'read_lat_p99': 500,
            'read_lat_p999': 600,
            'write_lat_p50': 1000,
            'write_lat_p99': 1100,
            'write_lat_p999': 1200,
            'metadata': mock_metadata,
            'raw_result': mock_raw_result,
            'run_url': run_url
        }

        written_content = mock_open_file().write.call_args[0][0]
        # Remove the newline that's added in the actual function
        written_json = written_content.rstrip('\n')
        self.assertEqual(json.loads(written_json), expected_result)

        # Verify logging
        mock_logger.info.assert_called_with(
            f"Results collected and saved to {result_dir}/results.json:\n{json.dumps(expected_result, indent=2)}"
        )

    @patch("fio.fio.validate")
    @patch("argparse.ArgumentParser.parse_args")
    def test_main_validate_command(self, mock_parse_args, mock_validate):
        """Test main function with validate command"""
        # Mock argparse to simulate command line arguments
        mock_args = MagicMock()
        mock_args.command = "validate"
        mock_args.node_count = 3
        mock_args.operation_timeout = 600
        mock_parse_args.return_value = mock_args

        main()

        mock_validate.assert_called_once_with(3, 600)

    @patch("argparse.ArgumentParser.parse_args")
    @patch("fio.fio.execute")
    def test_main_execute_command(self, mock_execute, mock_parse_args):
        """Test main function with execute command"""
        # Mock argparse to simulate command line arguments
        mock_args = MagicMock()
        mock_args.command = "execute"
        mock_args.block_size = "4k"
        mock_args.iodepth = 16
        mock_args.method = "read"
        mock_args.runtime = 60
        mock_args.numjobs = 1
        mock_args.file_size = "10G"
        mock_args.storage_name = "fio"
        mock_args.kustomize_dir = "/tmp/kustomize"
        mock_args.result_dir = "/tmp/results"
        mock_parse_args.return_value = mock_args

        main()

        mock_execute.assert_called_once_with(
            "4k", 16, "read", 60, 1, "10G", "fio", "/tmp/kustomize", "/tmp/results"
        )

    @patch("argparse.ArgumentParser.parse_args")
    @patch("fio.fio.collect")
    def test_main_collect_command(self, mock_collect, mock_parse_args):
        """Test main function with collect command"""
        # Mock argparse to simulate command line arguments
        mock_args = MagicMock()
        mock_args.command = "collect"
        mock_args.vm_size = "Standard_D8s_v3"
        mock_args.block_size = "4k"
        mock_args.iodepth = 16
        mock_args.method = "read"
        mock_args.numjobs = 1
        mock_args.file_size = "10G"
        mock_args.result_dir = "/tmp/results"
        mock_args.run_url = "http://test.com/run"
        mock_args.cloud_info = '{"cloud": "azure"}'
        mock_parse_args.return_value = mock_args

        main()

        mock_collect.assert_called_once_with(
            "Standard_D8s_v3",
            "4k",
            16,
            "read",
            1,
            "10G",
            "/tmp/results",
            "http://test.com/run",
            '{"cloud": "azure"}',
        )

    @patch("argparse.ArgumentParser.parse_args")
    def test_main_no_command(self, mock_parse_args):
        """Test main function with no command specified"""
        # Mock argparse to simulate no command
        mock_args = MagicMock()
        mock_args.command = None
        mock_parse_args.return_value = mock_args

        # Should complete without error when no command is specified
        main()

if __name__ == '__main__':
    unittest.main()
