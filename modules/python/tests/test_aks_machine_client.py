"""Tests for AKSMachineClient (composes AKSClient)."""
from unittest.mock import patch, MagicMock

from clients.aks_machine_client import AKSMachineClient


def test_compose_aksclient_not_subclass():
    """Verify AKSMachineClient composes (does NOT inherit from) AKSClient."""
    from clients.aks_client import AKSClient
    assert AKSClient not in AKSMachineClient.__mro__
    assert AKSClient not in AKSMachineClient.__bases__


@patch("clients.aks_machine_client.AKSClient")
def test_get_access_token_uses_aks_client_credential(MockAKS):
    fake_cred = MagicMock()
    fake_cred.get_token.return_value.token = "tok"
    MockAKS.return_value.credential = fake_cred
    c = AKSMachineClient(resource_group="rg")
    assert c._get_access_token() == "tok"
    fake_cred.get_token.assert_called_once_with("https://management.azure.com/.default")


@patch("clients.aks_machine_client.requests.request")
@patch("clients.aks_machine_client.AKSClient")
def test_make_request_sets_bearer_and_returns_response(MockAKS, mock_req):
    MockAKS.return_value.credential.get_token.return_value.token = "T"
    mock_req.return_value = MagicMock(status_code=200, json=lambda: {"ok": 1})
    c = AKSMachineClient(resource_group="rg")
    r = c.make_request("PUT", "https://x", data={"a": 1}, timeout=10)
    args, kw = mock_req.call_args
    assert kw["headers"]["Authorization"] == "Bearer T"
    assert kw["headers"]["Content-Type"] == "application/json"
    assert kw["json"] == {"a": 1}
    assert kw["timeout"] == 10
    assert r.status_code == 200
