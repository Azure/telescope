#!/usr/bin/env python3
"""Unit tests for MachineCRUD (thin try/except wrapper around AKSMachineClient).

MachineCRUD mirrors NodePoolCRUD: each public method forwards kwargs to the
underlying ``AKSMachineClient`` and converts exceptions into a False return.
All telemetry recording happens inside the client via OperationContext, so
these tests only verify forwarding + error swallowing.
"""
import unittest
from unittest import mock


class TestMachineCRUD(unittest.TestCase):
    """Tests for the MachineCRUD orchestrator class."""

    def setUp(self):
        self.client_patcher = mock.patch(
            "crud.azure.machine_crud.AKSMachineClient"
        )
        mock_client_class = self.client_patcher.start()
        self.mock_client = mock_client_class.return_value
        self.mock_client.get_cluster_name.return_value = "fake-cluster"

        # Import lazily so the patch above is in effect.
        from crud.azure.machine_crud import MachineCRUD  # pylint: disable=import-outside-toplevel
        self.crud = MachineCRUD(
            resource_group="fake-rg",
            kube_config_file=None,
            result_dir="/tmp/test_results",
            step_timeout=900,
        )

    def tearDown(self):
        self.client_patcher.stop()

    def test_init_captures_cluster_name(self):
        self.assertEqual(self.crud.cluster_name, "fake-cluster")
        self.assertEqual(self.crud.result_dir, "/tmp/test_results")
        self.assertEqual(self.crud.step_timeout, 900)

    # ---- create_machine_agentpool ----

    def test_create_machine_agentpool_forwards_kwargs(self):
        self.mock_client.create_machine_agentpool.return_value = True

        result = self.crud.create_machine_agentpool(
            agent_pool_name="apool", vm_size="Standard_D2_v3"
        )

        self.assertTrue(result)
        self.mock_client.create_machine_agentpool.assert_called_once_with(
            agent_pool_name="apool",
            vm_size="Standard_D2_v3",
            cluster_name="fake-cluster",
            timeout=900,
        )

    def test_create_machine_agentpool_swallows_exception(self):
        self.mock_client.create_machine_agentpool.side_effect = RuntimeError("boom")
        result = self.crud.create_machine_agentpool(
            agent_pool_name="apool", vm_size="Standard_D2_v3"
        )
        self.assertFalse(result)

    # ---- scale_machine ----

    def test_scale_machine_forwards_all_kwargs(self):
        self.mock_client.scale_machine.return_value = True

        result = self.crud.scale_machine(
            agent_pool_name="apool",
            vm_size="Standard_D2_v3",
            scale_machine_count=50,
            use_batch_api=True,
            machine_workers=4,
            readiness_wait_timeout=1800,
            tags={"owner": "perf"},
        )

        self.assertTrue(result)
        self.mock_client.scale_machine.assert_called_once_with(
            agent_pool_name="apool",
            vm_size="Standard_D2_v3",
            scale_machine_count=50,
            cluster_name="fake-cluster",
            use_batch_api=True,
            machine_workers=4,
            timeout=900,
            readiness_wait_timeout=1800,
            tags={"owner": "perf"},
        )

    def test_scale_machine_defaults_match_signature(self):
        self.mock_client.scale_machine.return_value = True

        self.crud.scale_machine(
            agent_pool_name="apool", vm_size="Standard_D2_v3",
            scale_machine_count=1,
        )

        kwargs = self.mock_client.scale_machine.call_args.kwargs
        self.assertEqual(kwargs["use_batch_api"], False)
        self.assertEqual(kwargs["machine_workers"], 1)
        self.assertEqual(kwargs["readiness_wait_timeout"], 1200)
        self.assertIsNone(kwargs["tags"])

    def test_scale_machine_swallows_exception(self):
        self.mock_client.scale_machine.side_effect = RuntimeError("boom")
        result = self.crud.scale_machine(
            agent_pool_name="apool", vm_size="Standard_D2_v3",
            scale_machine_count=1,
        )
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
