"""Tests for Azure node-pool CLI helpers."""

import unittest
from unittest import mock

from azure.mgmt.containerservice.models import (
    ManualScaleProfile,
    ScaleProfile,
    VirtualMachinesProfile,
)

from utils.azure_node_pool_cli import (
    build_add_virtual_machines_command,
    build_scale_virtual_machines_command,
    get_node_pool_scale_state,
    prepare_create_operation,
    prepare_scale_operation,
)


class TestAzureNodePoolCLI(unittest.TestCase):
    """Validate VirtualMachines readback and command contracts."""

    def test_get_scale_state_from_sdk_model(self):
        node_pool = mock.MagicMock()
        node_pool.virtual_machines_profile = VirtualMachinesProfile(
            scale=ScaleProfile(
                manual=[
                    ManualScaleProfile(size="Standard_D2s_v3", count=2),
                    ManualScaleProfile(size="Standard_D4s_v3", count=3),
                ]
            )
        )

        count, vm_size = get_node_pool_scale_state(node_pool, "VirtualMachines")

        self.assertEqual(count, 5)
        self.assertEqual(vm_size, "Standard_D2s_v3")

    def test_get_scale_state_from_dict(self):
        node_pool = mock.MagicMock()
        node_pool.virtual_machines_profile = {
            "scale": {
                "manual": [{"size": "Standard_D2s_v3", "count": 2}]
            }
        }

        count, vm_size = get_node_pool_scale_state(node_pool, "VirtualMachines")

        self.assertEqual(count, 2)
        self.assertEqual(vm_size, "Standard_D2s_v3")

    def test_build_add_virtual_machines_command(self):
        command = build_add_virtual_machines_command(
            "test-rg", "test-cluster", "test-pool", 2, "Standard_D2s_v3"
        )

        self.assertEqual(
            command,
            [
                "az", "aks", "nodepool", "add",
                "--resource-group", "test-rg",
                "--cluster-name", "test-cluster",
                "--name", "test-pool",
                "--node-count", "2",
                "--vm-sizes", "Standard_D2s_v3",
                "--vm-set-type", "VirtualMachines",
                "--mode", "User",
                "--node-osdisk-type", "Managed",
            ],
        )

    def test_build_scale_virtual_machines_command(self):
        command = build_scale_virtual_machines_command(
            "test-rg", "test-cluster", "test-pool", 3
        )

        self.assertEqual(
            command,
            [
                "az", "aks", "nodepool", "scale",
                "--resource-group", "test-rg",
                "--cluster-name", "test-cluster",
                "--name", "test-pool",
                "--node-count", "3",
            ],
        )

    def test_prepare_create_operation_returns_vmss_callable(self):
        parameters = {}
        aks_sdk_client = mock.MagicMock()
        aks_sdk_client.agent_pools.begin_create_or_update.return_value.done.return_value = True

        operation = prepare_create_operation(
            parameters,
            "VirtualMachineScaleSets",
            False,
            "test-rg",
            "test-cluster",
            "test-pool",
            2,
            "Standard_D2s_v3",
            aks_sdk_client,
        )

        self.assertTrue(callable(operation))
        operation()
        call_parameters = (
            aks_sdk_client.agent_pools.begin_create_or_update.call_args.kwargs[
                "parameters"
            ]
        )
        self.assertEqual(call_parameters, {"count": 2, "vm_size": "Standard_D2s_v3"})

    def test_prepare_create_operation_returns_virtual_machines_callable(self):
        operation = prepare_create_operation(
            {},
            "VirtualMachines",
            False,
            "test-rg",
            "test-cluster",
            "test-pool",
            2,
            "Standard_D2s_v3",
            mock.MagicMock(),
        )

        self.assertTrue(callable(operation))

    def test_prepare_scale_operation_returns_vmss_callable(self):
        node_pool = mock.MagicMock()
        aks_sdk_client = mock.MagicMock()
        aks_sdk_client.agent_pools.begin_create_or_update.return_value.done.return_value = True

        operation = prepare_scale_operation(
            node_pool,
            "VirtualMachineScaleSets",
            "test-rg",
            "test-cluster",
            "test-pool",
            3,
            aks_sdk_client,
        )

        self.assertTrue(callable(operation))
        self.assertEqual(node_pool.count, 3)
        operation()
        aks_sdk_client.agent_pools.begin_create_or_update.assert_called_once()

    def test_prepare_scale_operation_returns_virtual_machines_callable(self):
        operation = prepare_scale_operation(
            mock.MagicMock(),
            "VirtualMachines",
            "test-rg",
            "test-cluster",
            "test-pool",
            3,
            mock.MagicMock(),
        )

        self.assertTrue(callable(operation))


if __name__ == "__main__":
    unittest.main()
