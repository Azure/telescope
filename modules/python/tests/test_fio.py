import unittest
import json
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, mock_open, call
from kubernetes.client import V1Pod, V1ObjectMeta, V1PodStatus, V1PodCondition

with patch("clients.kubernetes_client.config.load_kube_config") as mock_load_kube_config:
    mock_load_kube_config.return_value = None

    from fio.fio import (
        configure, execute, collect
    )

class TestFio(unittest.TestCase):
    def setUp(self):
        self.mock_kubernetes_client = MagicMock()
        self.mock_logger = MagicMock()

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
            "storage_name": "fio",
            "start_time": time.time(),
            "end_time": time.time() + 60
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
        self.assertEqual(json.loads(written_content), expected_result)

        # Verify logging
        mock_logger.info.assert_called_with(
            f"Results collected and saved to {result_dir}/results.json:\n{json.dumps(expected_result, indent=2)}"
        )

if __name__ == '__main__':
    unittest.main()
