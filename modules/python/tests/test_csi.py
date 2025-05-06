import unittest
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, mock_open
from kubernetes.client.models import (
    V1StatefulSet,
    V1ObjectMeta,
    V1StatefulSetSpec,
    V1LabelSelector,
    V1PodTemplateSpec,
    V1PodSpec,
    V1Container,
    V1VolumeMount,
    V1PersistentVolumeClaimTemplate,
    V1PersistentVolumeClaimSpec,
    V1ResourceRequirements
)

with patch("clusterloader2.kubernetes_client.config.load_kube_config") as mock_load_kube_config:
    # Mock the load_kube_config function to do nothing
    mock_load_kube_config.return_value = None

    # Now import the module where the global KUBERNETERS_CLIENT is defined
    from csi.csi import (
        wait_for_condition, calculate_percentiles, log_duration,
        create_statefulset, collect_attach_detach
    )

class TestCSI(unittest.TestCase):

    def test_calculate_percentiles(self):
        disk_numbers = [300, 1000]
        expected_percentiles = {
            300: [150, 270, 297, 300],
            1000: [500, 900, 990, 1000]
        }
        for disk_number in disk_numbers:
            p50, p90, p99, p100 = calculate_percentiles(disk_number)
            self.assertEqual(p50, expected_percentiles[disk_number][0])
            self.assertEqual(p90, expected_percentiles[disk_number][1])
            self.assertEqual(p99, expected_percentiles[disk_number][2])
            self.assertEqual(p100, expected_percentiles[disk_number][3])

    @patch("builtins.open", new_callable=mock_open)
    @patch("csi.csi.datetime")
    def test_log_duration_success(self, mock_datetime, mock_open_file):
        duration = 200
        # Mock start_time and end_time
        mock_start_time = datetime(2024, 1, 1, 12, 0, 0)  # Fixed start time
        mock_end_time = mock_start_time + timedelta(seconds=duration)  # Fixed end time

        # Mock datetime.now to return the end_time
        mock_datetime.now.return_value = mock_end_time

        # Call the function
        log_file = "log.txt"
        description = "PV creation p99"
        log_duration(description, mock_start_time, log_file)

        # Verify file write
        mock_open_file.assert_called_once_with(log_file, "a", encoding='utf-8')
        mock_open_file().write.assert_called_once_with(f"{description}: {duration}\n")

        # Verify print output
        with patch("builtins.print") as mock_print:
            log_duration(description, mock_start_time, log_file)
            mock_print.assert_called_with(f"{description}: {duration}s")

    def test_log_duration_failure(self):
        # Test that an exception is raised when the description contains ":"
        start_time = datetime.now()
        log_file = "log.txt"
        description = "Invalid:Description"

        with self.assertRaises(Exception) as context:
            log_duration(description, start_time, log_file)

        self.assertEqual(
            str(context.exception), "Description cannot contain a colon ':' character!"
        )

    def test_wait_for_condition_met_immediately(self):
        check_function = MagicMock(return_value=[f"disk-{i}" for i in range(3)])
        result = wait_for_condition(check_function, 3, "gte", 1)
        self.assertEqual(result, 3)
        check_function.assert_called_once()

        check_function.reset_mock()
        check_function.return_value = [f"disk-{i}" for i in range(4)]
        result = wait_for_condition(check_function, 5, "lte", 1)
        self.assertEqual(result, 4)
        check_function.assert_called_once()

    def test_wait_for_condition_met_after_iterations(self):
        check_function = MagicMock(side_effect=[
            [f"disk-{i}" for i in range(1)],
            [f"disk-{i}" for i in range(2)],
            [f"disk-{i}" for i in range(3)]
        ])
        result = wait_for_condition(check_function, 3, "gte", 1)
        self.assertEqual(result, 3)
        self.assertEqual(check_function.call_count, 3)

        check_function.reset_mock()
        check_function.side_effect = [
            [f"disk-{i}" for i in range(7)],
            [f"disk-{i}" for i in range(6)],
            [f"disk-{i}" for i in range(5)]
        ]
        result = wait_for_condition(check_function, 5, "lte", 1)
        self.assertEqual(result, 5)
        self.assertEqual(check_function.call_count, 3)

    @patch("clusterloader2.kubernetes_client.KubernetesClient.get_app_client")
    def test_create_statefulset_success(self, mock_get_app_client):
        namespace = "test"
        replicas = 10
        storage_class = "default"
        expected_statefulset = V1StatefulSet(
            api_version="apps/v1",
            kind="StatefulSet",
            metadata=V1ObjectMeta(name="statefulset-local"),
            spec=V1StatefulSetSpec(
                pod_management_policy="Parallel",
                replicas=replicas,
                selector=V1LabelSelector(match_labels={"app": "nginx"}),
                service_name="statefulset-local",
                template=V1PodTemplateSpec(
                    metadata=V1ObjectMeta(labels={"app": "nginx"}),
                    spec=V1PodSpec(
                        node_selector={"kubernetes.io/os": "linux"},
                        containers=[
                            V1Container(
                                name="statefulset-local",
                                image="mcr.microsoft.com/oss/nginx/nginx:1.19.5",
                                command=[
                                    "/bin/bash",
                                    "-c",
                                    "set -euo pipefail; while true; do echo $(date) >> /mnt/local/outfile; sleep 1; done",
                                ],
                                volume_mounts=[
                                    V1VolumeMount(
                                        name="persistent-storage", mount_path="/mnt/local"
                                    )
                                ],
                            )
                        ],
                    ),
                ),
                volume_claim_templates=[
                    V1PersistentVolumeClaimTemplate(
                        metadata=V1ObjectMeta(
                            name="persistent-storage",
                            annotations={"volume.beta.kubernetes.io/storage-class": storage_class},
                        ),
                        spec=V1PersistentVolumeClaimSpec(
                            access_modes=["ReadWriteOnce"],
                            resources=V1ResourceRequirements(requests={"storage": "1Gi"}),
                        ),
                    )
                ],
            ),
        )

        mock_app_client = MagicMock()
        mock_get_app_client.return_value = mock_app_client
        mock_app_client.create_namespaced_stateful_set.return_value = expected_statefulset

        actual_statefulset = create_statefulset(namespace, replicas, storage_class)

        mock_get_app_client.assert_called_once()
        mock_app_client.create_namespaced_stateful_set.assert_called_once_with(
            namespace, expected_statefulset
        )
        self.assertEqual(actual_statefulset, expected_statefulset)

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    @patch("os.path.join")
    @patch("csi.csi.datetime")
    def test_collect_attach_detach_results(
        self, mock_datetime, mock_path_join, mock_makedirs, mock_open_file
    ):
        result_dir = "result_dir"
        case_name = "Standard_D16s_v3_1000pods_40nodes"
        node_number = 40
        disk_number = 1000
        storage_class = "default"
        cloud_info = {"cloud": "azure"}
        run_id = "12345789"
        run_url = "http://example.com/test-run"

        mock_path_join.side_effect = lambda *args: "/".join(args)
        raw_result_file = f"{result_dir}/attachdetach-{disk_number}.txt"
        result_file = f"{result_dir}/results.json"

        mock_timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_timestamp

        raw_file_content = """
PV creation p50: 178
PV creation p90: 240
PV creation p99: 252
PV creation p100: 253
PV attachment p50: 261
PV attachment p90: 347
PV attachment p99: 359
PV attachment p100: 367
PV detachment p50: 211
PV detachment p90: 281
PV detachment p99: 401
PV detachment p100: 412
"""
        mock_open_file().read.return_value = raw_file_content

        collect_attach_detach(
            case_name,
            node_number,
            disk_number,
            storage_class,
            cloud_info,
            run_id,
            run_url,
            result_dir
        )

        mock_makedirs.assert_called_once_with(result_dir, exist_ok=True)

        mock_open_file.assert_any_call(raw_result_file, 'r', encoding='utf-8')
        mock_open_file().read.assert_called_once()

        expected_metrics = {
            "PV_creation_p50": "178",
            "PV_creation_p90": "240",
            "PV_creation_p99": "252",
            "PV_creation_p100": "253",
            "PV_attachment_p50": "261",
            "PV_attachment_p90": "347",
            "PV_attachment_p99": "359",
            "PV_attachment_p100": "367",
            "PV_detachment_p50": "211",
            "PV_detachment_p90": "281",
            "PV_detachment_p99": "401",
            "PV_detachment_p100": "412",
        }

        mock_open_file.assert_any_call(result_file, 'w', encoding='utf-8')
        written_content = mock_open_file().write.call_args[0][0]
        written_json = json.loads(written_content)

        expected_content = {
            "timestamp": mock_timestamp.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "case_name": case_name,
            "node_number": node_number,
            "disk_number": disk_number,
            "storage_class": storage_class,
            "result": expected_metrics,
            "cloud_info": cloud_info,
            "run_id": run_id,
            "run_url": run_url,
        }

        self.maxDiff = None # pylint: disable=invalid-name
        self.assertEqual(written_json, expected_content)

if __name__ == '__main__':
    unittest.main()