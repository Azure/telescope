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
    args, _ = mock_req.call_args
    assert args == ("PUT", "https://x")


@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_create_machine_agentpool_puts_with_mode_machines(MockAKS, mock_req):
    MockAKS.return_value.subscription_id = "SUB"
    mock_req.side_effect = [
        MagicMock(status_code=201, json=lambda: {"properties": {"provisioningState": "Creating"}}),
        MagicMock(status_code=200, json=lambda: {"properties": {"provisioningState": "Succeeded"}}),
    ]
    c = AKSMachineClient(resource_group="rg")
    ok = c.create_machine_agentpool("apool", "cl", "rg", timeout=30)
    assert ok is True
    put_call = mock_req.call_args_list[0]
    assert put_call.args[0] == "PUT"
    assert "/managedClusters/cl/agentPools/apool" in put_call.args[1]
    assert put_call.kwargs["data"]["properties"]["mode"] == "Machines"


@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_create_machine_agentpool_returns_false_on_put_failure(MockAKS, mock_req, _sleep):
    MockAKS.return_value.subscription_id = "SUB"
    mock_req.return_value = MagicMock(status_code=400, text="bad request")
    c = AKSMachineClient(resource_group="rg")
    assert c.create_machine_agentpool("apool", "cl", "rg", timeout=30) is False
    # Only the PUT was attempted; no GET poll.
    assert mock_req.call_count == 1


@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_create_machine_agentpool_returns_false_on_failed_state(MockAKS, mock_req, _sleep):
    MockAKS.return_value.subscription_id = "SUB"
    mock_req.side_effect = [
        MagicMock(status_code=201, json=lambda: {"properties": {"provisioningState": "Creating"}}),
        MagicMock(status_code=200, json=lambda: {"properties": {"provisioningState": "Failed"}}),
    ]
    c = AKSMachineClient(resource_group="rg")
    assert c.create_machine_agentpool("apool", "cl", "rg", timeout=30) is False


@patch("clients.aks_machine_client.time.time")
@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_create_machine_agentpool_returns_false_on_timeout(MockAKS, mock_req, _sleep, mock_time):
    # First call seeds deadline (t=0 -> deadline=30). Second call (loop check) returns 0 (passes).
    # Third onward returns 100 (past deadline). Use closure since logging also calls time.time().
    _calls = {"n": 0}

    def _fake_time():
        _calls["n"] += 1
        if _calls["n"] == 1:
            return 0  # initial deadline computation
        if _calls["n"] == 2:
            return 0  # first while-loop check (still within deadline)
        return 100  # subsequent calls -> past deadline

    mock_time.side_effect = _fake_time
    MockAKS.return_value.subscription_id = "SUB"
    mock_req.side_effect = [
        MagicMock(status_code=201, json=lambda: {"properties": {"provisioningState": "Creating"}}),
        MagicMock(status_code=200, json=lambda: {"properties": {"provisioningState": "Creating"}}),
    ]
    c = AKSMachineClient(resource_group="rg")
    assert c.create_machine_agentpool("apool", "cl", "rg", timeout=30) is False


@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_machine_node_readiness_computes_percentiles(MockAKS):
    fake_kc = MagicMock()
    # Each call returns a node with conditions list; we pretend all 4 are ready immediately.
    def details(name):
        return {"status": {"conditions": [{"type": "Ready", "status": "True",
                                            "lastTransitionTime": "2026-05-05T10:00:00Z"}]}}
    fake_kc.get_node_details.side_effect = details
    MockAKS.return_value.kubernetes_client = fake_kc
    c = AKSMachineClient(resource_group="rg")
    times = c._wait_for_machine_node_readiness(
        machine_names=["m1", "m2", "m3", "m4"],
        start_time_utc="2026-05-05T09:59:50Z",
        timeout=5,
    )
    assert set(times.keys()) == {"P50", "P90", "P99"}
    assert all(times[p] >= 0 for p in times)


@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_machine_node_readiness_empty_machine_names(MockAKS):
    fake_kc = MagicMock()
    MockAKS.return_value.kubernetes_client = fake_kc
    c = AKSMachineClient(resource_group="rg")
    times = c._wait_for_machine_node_readiness(
        machine_names=[],
        start_time_utc="2026-05-05T09:59:50Z",
        timeout=5,
    )
    assert times == {"P50": 0.0, "P90": 0.0, "P99": 0.0}
    fake_kc.get_node_details.assert_not_called()


@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_machine_node_readiness_kubernetes_client_none(MockAKS):
    MockAKS.return_value.kubernetes_client = None
    c = AKSMachineClient(resource_group="rg")
    times = c._wait_for_machine_node_readiness(
        machine_names=["m1"],
        start_time_utc="2026-05-05T09:59:50Z",
        timeout=5,
    )
    assert times == {"P50": 0.0, "P90": 0.0, "P99": 0.0}


@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_machine_node_readiness_malformed_start_time(MockAKS):
    fake_kc = MagicMock()
    MockAKS.return_value.kubernetes_client = fake_kc
    c = AKSMachineClient(resource_group="rg")
    times = c._wait_for_machine_node_readiness(
        machine_names=["m1"],
        start_time_utc="not-a-timestamp",
        timeout=5,
    )
    assert times == {"P50": 0.0, "P90": 0.0, "P99": 0.0}
    fake_kc.get_node_details.assert_not_called()


@patch("clients.aks_machine_client.time.sleep")
@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_machine_node_readiness_get_node_details_raises(MockAKS, _sleep):
    fake_kc = MagicMock()
    fake_kc.get_node_details.side_effect = RuntimeError("boom")
    MockAKS.return_value.kubernetes_client = fake_kc
    c = AKSMachineClient(resource_group="rg")
    times = c._wait_for_machine_node_readiness(
        machine_names=["m1"],
        start_time_utc="2026-05-05T09:59:50Z",
        timeout=0,  # exit immediately after one iteration
    )
    assert times == {"P50": 0.0, "P90": 0.0, "P99": 0.0}
