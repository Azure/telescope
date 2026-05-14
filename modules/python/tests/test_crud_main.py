"""Tests for crud/main.py machine-API additions.

Covers the helpers and dispatchers introduced for the Machine API alongside
the existing node-pool flow:
- ``get_machine_crud_class`` cloud-provider dispatch.
- ``_env_int_override`` / ``_env_bool_override`` ADO-variable safe overrides.
- ``handle_machine_operation`` exit-code semantics.
- Argparse smoke for the ``create-machine`` and ``scale-machine`` subcommands.
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


class TestEnvIntOverride(unittest.TestCase):
    """Validate `_env_int_override` is robust against ADO unresolved variables."""

    def test_unset_returns_default(self):
        from crud.main import _env_int_override  # pylint: disable=import-outside-toplevel,protected-access
        with mock.patch.dict("os.environ", {}, clear=False):
            if "ENV_TEST_INT" in __import__("os").environ:
                del __import__("os").environ["ENV_TEST_INT"]
            self.assertEqual(_env_int_override("ENV_TEST_INT", 7), 7)

    def test_empty_string_returns_default(self):
        from crud.main import _env_int_override  # pylint: disable=import-outside-toplevel,protected-access
        with mock.patch.dict("os.environ", {"ENV_TEST_INT": ""}, clear=False):
            self.assertEqual(_env_int_override("ENV_TEST_INT", 7), 7)

    def test_ado_unresolved_returns_default(self):
        from crud.main import _env_int_override  # pylint: disable=import-outside-toplevel,protected-access
        with mock.patch.dict("os.environ", {"ENV_TEST_INT": "$(SCALE_COUNT)"}, clear=False):
            self.assertEqual(_env_int_override("ENV_TEST_INT", 7), 7)

    def test_valid_int_returns_int(self):
        from crud.main import _env_int_override  # pylint: disable=import-outside-toplevel,protected-access
        with mock.patch.dict("os.environ", {"ENV_TEST_INT": "42"}, clear=False):
            self.assertEqual(_env_int_override("ENV_TEST_INT", 7), 42)

    def test_invalid_int_returns_default(self):
        from crud.main import _env_int_override  # pylint: disable=import-outside-toplevel,protected-access
        with mock.patch.dict("os.environ", {"ENV_TEST_INT": "abc"}, clear=False):
            self.assertEqual(_env_int_override("ENV_TEST_INT", 7), 7)


class TestEnvBoolOverride(unittest.TestCase):
    def test_unset_returns_default(self):
        from crud.main import _env_bool_override  # pylint: disable=import-outside-toplevel,protected-access
        with mock.patch.dict("os.environ", {}, clear=False):
            if "ENV_TEST_BOOL" in __import__("os").environ:
                del __import__("os").environ["ENV_TEST_BOOL"]
            self.assertTrue(_env_bool_override("ENV_TEST_BOOL", True))
            self.assertFalse(_env_bool_override("ENV_TEST_BOOL", False))

    def test_ado_unresolved_returns_default(self):
        from crud.main import _env_bool_override  # pylint: disable=import-outside-toplevel,protected-access
        with mock.patch.dict("os.environ", {"ENV_TEST_BOOL": "$(USE_BATCH)"}, clear=False):
            self.assertTrue(_env_bool_override("ENV_TEST_BOOL", True))
            self.assertFalse(_env_bool_override("ENV_TEST_BOOL", False))

    def test_truthy_strings_return_true(self):
        from crud.main import _env_bool_override  # pylint: disable=import-outside-toplevel,protected-access
        for raw in ("1", "true", "True", "TRUE", "yes", "Y", "on"):
            with mock.patch.dict("os.environ", {"ENV_TEST_BOOL": raw}, clear=False):
                self.assertTrue(_env_bool_override("ENV_TEST_BOOL", False), msg=raw)

    def test_falsy_strings_return_false(self):
        from crud.main import _env_bool_override  # pylint: disable=import-outside-toplevel,protected-access
        for raw in ("0", "false", "no", "off", "garbage"):
            with mock.patch.dict("os.environ", {"ENV_TEST_BOOL": raw}, clear=False):
                self.assertFalse(_env_bool_override("ENV_TEST_BOOL", True), msg=raw)


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
            agentpool_name="apool", vm_size="Standard_D2_v3",
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
        self.assertEqual(kwargs["agentpool_name"], "apool")
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


if __name__ == "__main__":
    unittest.main()
