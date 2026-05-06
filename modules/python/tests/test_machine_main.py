import os, pytest
from unittest.mock import patch
from machine.main import build_parser, _env_int_override, _env_bool_override


def test_kebab_case_flags_only():
    p = build_parser()
    parsed = p.parse_args([
        "create",
        "--cloud", "azure",
        "--run-id", "RID",
        "--region", "eastus",
        "--node-pool-name", "smallpool1",
        "--vm-size", "Standard_D2_v3",
        "--scale-machine-count", "1",
        "--machine-workers", "1",
        "--use-batch-api", "false",
        "--step-timeout", "600",
        "--result-dir", "/tmp/x",
    ])
    assert parsed.cloud == "azure"
    assert parsed.scale_machine_count == 1

def test_argparse_rejects_delete_subcommand():
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["delete", "--cloud", "azure", "--run-id", "X"])

def test_env_int_override_picks_env_when_valid(monkeypatch):
    monkeypatch.setenv("ENV_FOO", "42")
    assert _env_int_override("ENV_FOO", default=1) == 42

def test_env_int_override_ignores_unresolved_dollar(monkeypatch):
    monkeypatch.setenv("ENV_FOO", "$(VAR)")
    assert _env_int_override("ENV_FOO", default=7) == 7

def test_env_int_override_ignores_non_digit(monkeypatch):
    monkeypatch.setenv("ENV_FOO", "abc")
    assert _env_int_override("ENV_FOO", default=9) == 9

def test_env_bool_override_handles_typical_truthy(monkeypatch):
    monkeypatch.setenv("ENV_FLAG", "True")
    assert _env_bool_override("ENV_FLAG", default=False) is True
    monkeypatch.setenv("ENV_FLAG", "$(X)")
    assert _env_bool_override("ENV_FLAG", default=True) is True  # falls through to default
