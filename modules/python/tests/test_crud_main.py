"""Tests for crud/main.py machine-API additions.

Covers the dispatchers introduced for the Machine API alongside the existing
node-pool flow:
- ``get_machine_crud_class`` cloud-provider dispatch.
- ``handle_machine_operation`` exit-code semantics.
- ``--tags`` JSON parsing by the scale-machine handler.
"""

import unittest
from types import SimpleNamespace
from unittest import mock


class TestGetMachineCrudClass(unittest.TestCase):
    def test_azure_returns_azure_machine_crud(self):
        from crud.main import get_machine_crud_class, AzureMachineCRUD  # pylint: disable=import-outside-toplevel
        self.assertIs(get_machine_crud_class("azure"), AzureMachineCRUD)

    def test_aws_raises_value_error(self):
        from crud.main import get_machine_crud_class  # pylint: disable=import-outside-toplevel
        with self.assertRaises(ValueError):
            get_machine_crud_class("aws")

    def test_gcp_raises_value_error(self):
        from crud.main import get_machine_crud_class  # pylint: disable=import-outside-toplevel
        with self.assertRaises(ValueError):
            get_machine_crud_class("gcp")


class TestHandleMachineOperation(unittest.TestCase):
    """Exit-code semantics: 0 on success, 1 on False return or exception."""

    def _make_args(self, command="create-machine", **overrides):
        defaults = {
            "command": command,
            "node_pool_name": "apool",
            "vm_size": "Standard_D2_v3",
            "scale_machine_count": 2,
            "machine_workers": 1,
            "use_batch_api": False,
            "readiness_wait_timeout": 1200,
            "aks_http_custom_features": None,
            "tags": None,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_create_machine_success_returns_zero(self):
        from crud.main import handle_machine_operation  # pylint: disable=import-outside-toplevel
        crud = mock.MagicMock()
        crud.create_machine_agentpool.return_value = True
        self.assertEqual(handle_machine_operation(crud, self._make_args()), 0)
        crud.create_machine_agentpool.assert_called_once_with(
            agent_pool_name="apool", vm_size="Standard_D2_v3",
        )

    def test_create_machine_false_returns_one(self):
        from crud.main import handle_machine_operation  # pylint: disable=import-outside-toplevel
        crud = mock.MagicMock()
        crud.create_machine_agentpool.return_value = False
        self.assertEqual(handle_machine_operation(crud, self._make_args()), 1)

    def test_scale_machine_success_returns_zero(self):
        from crud.main import handle_machine_operation  # pylint: disable=import-outside-toplevel
        crud = mock.MagicMock()
        crud.scale_machine.return_value = True
        self.assertEqual(
            handle_machine_operation(crud, self._make_args(command="scale-machine")), 0,
        )
        crud.scale_machine.assert_called_once()
        kwargs = crud.scale_machine.call_args.kwargs
        self.assertEqual(kwargs["agent_pool_name"], "apool")
        self.assertEqual(kwargs["scale_machine_count"], 2)

    def test_scale_machine_unknown_command_returns_one(self):
        from crud.main import handle_machine_operation  # pylint: disable=import-outside-toplevel
        crud = mock.MagicMock()
        self.assertEqual(
            handle_machine_operation(crud, self._make_args(command="bogus")), 1,
        )

    def test_scale_machine_exception_returns_one(self):
        from crud.main import handle_machine_operation  # pylint: disable=import-outside-toplevel
        crud = mock.MagicMock()
        crud.scale_machine.side_effect = RuntimeError("boom")
        self.assertEqual(
            handle_machine_operation(crud, self._make_args(command="scale-machine")), 1,
        )

    def test_scale_machine_parses_json_tags(self):
        from crud.main import handle_machine_operation  # pylint: disable=import-outside-toplevel
        crud = mock.MagicMock()
        crud.scale_machine.return_value = True
        args = self._make_args(command="scale-machine", tags='{"owner": "telescope"}')
        self.assertEqual(handle_machine_operation(crud, args), 0)
        kwargs = crud.scale_machine.call_args.kwargs
        self.assertEqual(kwargs["tags"], {"owner": "telescope"})

    def test_scale_machine_forwards_aks_http_custom_features(self):
        from crud.main import handle_machine_operation  # pylint: disable=import-outside-toplevel
        crud = mock.MagicMock()
        crud.scale_machine.return_value = True
        args = self._make_args(
            command="scale-machine",
            aks_http_custom_features="DisableSelfContainedVHD",
        )
        self.assertEqual(handle_machine_operation(crud, args), 0)
        kwargs = crud.scale_machine.call_args.kwargs
        self.assertEqual(
            kwargs["aks_http_custom_features"], "DisableSelfContainedVHD"
        )


if __name__ == "__main__":
    unittest.main()
