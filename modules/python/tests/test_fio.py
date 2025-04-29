import unittest
import json
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, mock_open, call
from kubernetes.client import V1Pod, V1ObjectMeta, V1PodStatus, V1PodCondition

with patch("clients.kubernetes_client.config.load_kube_config") as mock_load_kube_config:
    mock_load_kube_config.return_value = None

    from fio.fio import (
        configure, execute, collect, FILE_SIZE
    )

class TestFio(unittest.TestCase):
    def setUp(self):
        self.mock_kubernetes_client = MagicMock()
        self.mock_logger = MagicMock()

    @patch('fio.fio.KUBERNETES_CLIENT')
    @patch('fio.fio.logger')
    def test_configure_success(self, mock_logger, mock_kubernetes_client):
        yaml_path = "test.yaml"
        replicas = 3
        timeout = 10

        # Create three proper V1Pod mocks with Ready condition
        mock_pods = []
        for i in range(replicas):
            mock_pod = V1Pod(
                metadata=V1ObjectMeta(name=f"test-pod-{i}"),
                status=V1PodStatus(
                    phase="Running",
                    conditions=[
                        V1PodCondition(
                            type="Ready",
                            status="True"
                        )
                    ]
                )
            )
            mock_pods.append(mock_pod)

        mock_kubernetes_client.create_template.return_value = "mock_template"
        mock_kubernetes_client.create_deployment.return_value = "test-deployment"
        mock_kubernetes_client.wait_for_pods_ready.return_value = mock_pods
        mock_kubernetes_client.get_pod_logs.return_value = "test logs"

        configure(yaml_path, replicas, timeout)

        mock_kubernetes_client.create_template.assert_called_once_with(
            yaml_path, {"REPLICAS": replicas}
        )
        mock_kubernetes_client.create_deployment.assert_called_once_with("mock_template")
        mock_kubernetes_client.wait_for_pods_ready.assert_called_once_with(
            label_selector="test=fio",
            pod_count=replicas,
            operation_timeout_in_minutes=timeout
        )

        # Verify that get_pod_logs was called for each pod
        expected_get_logs_calls = [call(f"test-pod-{i}") for i in range(replicas)]
        mock_kubernetes_client.get_pod_logs.assert_has_calls(expected_get_logs_calls)
        self.assertEqual(mock_kubernetes_client.get_pod_logs.call_count, replicas)

        # Verify logging calls for each pod
        expected_log_calls = [
            call("Deployment test-deployment created successfully!")
        ] + [
            call(f"Checking logs for pod test-pod-{i}:\ntest logs")
            for i in range(replicas)
        ]
        mock_logger.info.assert_has_calls(expected_log_calls)

    @patch('fio.fio.KUBERNETES_CLIENT')
    @patch('fio.fio.logger')
    def test_configure_failure_wrong_replicas(self, _mock_logger, mock_kubernetes_client):
        # Test parameters
        yaml_path = "test.yaml"
        replicas = 2
        timeout = 10

        # Create a single ready pod to simulate partial success
        mock_pod = V1Pod(
            metadata=V1ObjectMeta(name="test-pod-1"),
            status=V1PodStatus(
                phase="Running",
                conditions=[
                    V1PodCondition(
                        type="Ready",
                        status="True"
                    )
                ]
            )
        )

        # Mock kubernetes client
        mock_kubernetes_client.create_template.return_value = "mock_template"
        mock_kubernetes_client.create_deployment.return_value = "test-deployment"

        # Simulate the timeout behavior where only one pod becomes ready
        def mock_get_pods(*_args, **_kwargs):
            return [mock_pod]  # Always return just one pod

        mock_kubernetes_client.get_ready_pods_by_namespace.side_effect = mock_get_pods
        mock_kubernetes_client.wait_for_pods_ready.side_effect = Exception("Only 1 pods are ready, expected 2 pods!")

        # Execute test and verify it raises an exception
        with self.assertRaises(Exception) as context:
            configure(yaml_path, replicas, timeout)

        self.assertEqual(str(context.exception), "Only 1 pods are ready, expected 2 pods!")

        # Verify the calls were made in order
        mock_kubernetes_client.create_template.assert_called_once_with(
            yaml_path, {"REPLICAS": replicas}
        )
        mock_kubernetes_client.create_deployment.assert_called_once_with("mock_template")
        mock_kubernetes_client.wait_for_pods_ready.assert_called_once_with(
            label_selector="test=fio",
            pod_count=replicas,
            operation_timeout_in_minutes=timeout
        )

        # Verify no logs were checked since we failed before that point
        mock_kubernetes_client.get_pod_logs.assert_not_called()

    @patch('builtins.open', new_callable=mock_open)
    @patch('fio.fio.time.sleep')
    @patch('fio.fio.time.time')
    @patch('fio.fio.execute_with_retries')
    @patch('fio.fio.os.makedirs')
    @patch('fio.fio.os.path.join')
    @patch('fio.fio.KUBERNETES_CLIENT')
    @patch('fio.fio.logger')
    def test_execute_success(self, _mock_logger, mock_kubernetes_client,
                           mock_path_join, mock_makedirs, mock_execute_with_retries,
                           mock_time, mock_sleep, mock_open_file):
        # Test parameters
        block_size = "4k"
        iodepth = 16
        method = "read"
        runtime = 60
        result_dir = "/tmp/results"

        # Mock time operations
        mock_time.side_effect = [100, 200]  # start_time, end_time

        # Mock path operations
        mock_path_join.side_effect = lambda *args: "/".join(args)

        # Mock pod setup
        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        mock_volume_mount = MagicMock()
        mock_volume_mount.mount_path = "/data"
        mock_pod.spec.containers = [MagicMock(volume_mounts=[mock_volume_mount])]
        mock_kubernetes_client.get_pods_by_namespace.return_value = [mock_pod]

        # Execute test
        execute(block_size, iodepth, method, runtime, result_dir)

        # Verify directory creation
        mock_makedirs.assert_called_once_with(result_dir, exist_ok=True)

        # Verify pod retrieval
        mock_kubernetes_client.get_pods_by_namespace.assert_called_once_with(
            namespace="default", label_selector="test=fio"
        )

        # Verify expected commands were executed
        expected_base_command = (
            f"fio --name=benchtest --size={FILE_SIZE} "
            f"--filename=/data/benchtest --direct=1 --ioengine=libaio "
            f"--time_based --rw={method} --bs={block_size} --iodepth={iodepth} "
            f"--runtime={runtime} --output-format=json"
        )
        expected_setup_command = f"{expected_base_command} --create_only=1"

        # Verify commands were executed with retries
        mock_execute_with_retries.assert_has_calls([
            call(
                mock_kubernetes_client.run_pod_exec_command,
                pod_name="test-pod",
                container_name="fio",
                command=expected_setup_command
            ),
            call(
                mock_kubernetes_client.run_pod_exec_command,
                pod_name="test-pod",
                container_name="fio",
                command=expected_base_command,
                dest_path=f"{result_dir}/fio-{block_size}-{iodepth}-{method}.json"
            )
        ])

        # Verify sleep was called
        mock_sleep.assert_called_once_with(30)

        # Verify metadata file was written
        expected_metadata = {
            "block_size": block_size,
            "iodepth": iodepth,
            "method": method,
            "file_size": FILE_SIZE,
            "runtime": runtime,
            "storage_name": "fio",
            "start_time": 100,
            "end_time": 200
        }

        metadata_path = f"{result_dir}/fio-{block_size}-{iodepth}-{method}-metadata.json"
        mock_open_file.assert_called_once_with(metadata_path, "w", encoding="utf-8")
        mock_open_file().write.assert_called_once_with(json.dumps(expected_metadata))

    @patch('builtins.open', new_callable=mock_open)
    @patch('fio.fio.datetime')
    @patch('fio.fio.logger')
    def test_collect_success(self, mock_logger, mock_datetime, mock_open_file):
        # Test parameters
        vm_size = "Standard_D8s_v3"
        block_size = "4k"
        iodepth = 16
        method = "read"
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
            "file_size": FILE_SIZE,
            "runtime": 60,
            "storage_name": "fio",
            "start_time": time.time(),
            "end_time": time.time() + 60
        }

        # Setup mock file reads
        mock_open_file.return_value.__enter__.return_value.read.side_effect = [
            json.dumps(mock_raw_result),
            json.dumps(mock_metadata)
        ]

        # Execute test
        collect(vm_size, block_size, iodepth, method, result_dir, run_url, cloud_info)

        # Verify file operations
        mock_open_file.assert_any_call(f"{result_dir}/fio-{block_size}-{iodepth}-{method}.json", "r", encoding="utf-8")
        mock_open_file.assert_any_call(f"{result_dir}/fio-{block_size}-{iodepth}-{method}-metadata.json", "r", encoding="utf-8")
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
        self.assertEqual(json.loads(written_content), expected_result)

        # Verify logging
        mock_logger.info.assert_called_with(
            f"Results collected and saved to {result_dir}/results.json:\n{json.dumps(expected_result, indent=2)}"
        )

if __name__ == '__main__':
    unittest.main()
