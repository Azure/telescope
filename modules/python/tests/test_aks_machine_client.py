"""Tests for AKSMachineClient (composes AKSClient)."""
from unittest.mock import patch, MagicMock

from clients.aks_machine_client import AKSMachineClient
from machine.data_classes import ScaleMachineRequest


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
    MockAKS.return_value.k8s_client = fake_kc
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
    MockAKS.return_value.k8s_client = fake_kc
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
    MockAKS.return_value.k8s_client = None
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
    MockAKS.return_value.k8s_client = fake_kc
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
    MockAKS.return_value.k8s_client = fake_kc
    c = AKSMachineClient(resource_group="rg")
    times = c._wait_for_machine_node_readiness(
        machine_names=["m1"],
        start_time_utc="2026-05-05T09:59:50Z",
        timeout=0,  # exit immediately after one iteration
    )
    assert times == {"P50": 0.0, "P90": 0.0, "P99": 0.0}


@patch.object(AKSMachineClient, "_wait_for_machine_node_readiness", return_value={"P50":1.0,"P90":2.0,"P99":3.0})
@patch.object(AKSMachineClient, "_create_single_machine")
@patch("clients.aks_machine_client.AKSClient")
def test_scale_machine_non_batch_dispatches_individual(MockAKS, mock_single, mock_wait):
    MockAKS.return_value.subscription_id = "SUB"
    mock_single.side_effect = lambda name, *a, **kw: name  # pretend success
    req = ScaleMachineRequest(cluster_name="c", resource_group="rg",
                              agentpool_name="ap", vm_size="Standard_D2_v3",
                              scale_machine_count=3, use_batch_api=False, machine_workers=2)
    c = AKSMachineClient(resource_group="rg")
    resp = c.scale_machine(req)
    assert mock_single.call_count == 3
    assert sorted(c_call.args[0] for c_call in mock_single.call_args_list) == [
        "tmach0000", "tmach0001", "tmach0002",
    ]
    assert resp.succeeded is True
    assert resp.percentile_node_readiness_times == {"P50":1.0,"P90":2.0,"P99":3.0}
    assert len(resp.successful_machines) == 3


@patch.object(AKSMachineClient, "_wait_for_machine_node_readiness", return_value={"P50":0.0,"P90":0.0,"P99":0.0})
@patch.object(AKSMachineClient, "_create_single_machine")
@patch("clients.aks_machine_client.AKSClient")
def test_scale_machine_non_batch_partial_failure(MockAKS, mock_single, mock_wait):
    """Worker-level outcomes (True/False/raise) must not escape; only True names count."""
    MockAKS.return_value.subscription_id = "SUB"

    def fake_single(name, *a, **kw):
        if name == "tmach0000":
            return True
        if name == "tmach0001":
            return False
        raise RuntimeError("boom")

    mock_single.side_effect = fake_single
    req = ScaleMachineRequest(cluster_name="c", resource_group="rg",
                              agentpool_name="ap", vm_size="Standard_D2_v3",
                              scale_machine_count=3, use_batch_api=False, machine_workers=2)
    c = AKSMachineClient(resource_group="rg")
    resp = c.scale_machine(req)
    assert mock_single.call_count == 3
    names_submitted = sorted(c_call.args[0] for c_call in mock_single.call_args_list)
    assert names_submitted == ["tmach0000", "tmach0001", "tmach0002"]
    assert resp.successful_machines == ["tmach0000"]
    assert resp.succeeded is False
    assert resp.error == ""


@patch.object(AKSMachineClient, "_wait_for_machine_node_readiness",
              return_value={"P50": 1.0, "P90": 1.0, "P99": 1.0})
@patch.object(AKSMachineClient, "_create_batch_machines")
@patch("clients.aks_machine_client.AKSClient")
def test_scale_machine_batch_dispatches_in_chunks(MockAKS, mock_create_batch, _mock_wait):
    """Batch path: 6 machines + 2 workers → 2 chunks of 3, all names submitted exactly once."""
    MockAKS.return_value.subscription_id = "SUB"
    mock_create_batch.side_effect = lambda request, chunk, chunk_idx: list(chunk)
    req = ScaleMachineRequest(
        cluster_name="cl", resource_group="rg", agentpool_name="ap",
        vm_size="Standard_D2_v3", scale_machine_count=6,
        use_batch_api=True, machine_workers=2,
    )
    c = AKSMachineClient(resource_group="rg")
    resp = c.scale_machine(req)

    assert mock_create_batch.call_count == 2
    expected_names = [f"tmach{i:04d}" for i in range(6)]
    submitted = sorted(n for call in mock_create_batch.call_args_list for n in call.args[1])
    assert submitted == sorted(expected_names)
    assert sorted(resp.successful_machines) == sorted(expected_names)
    assert set(resp.batch_command_execution_times.keys()) == {"chunk_0", "chunk_1"}
    assert all(v >= 0.0 for v in resp.batch_command_execution_times.values())
    assert resp.succeeded is True
    assert resp.percentile_node_readiness_times == {"P50": 1.0, "P90": 1.0, "P99": 1.0}


@patch.object(AKSMachineClient, "_wait_for_machine_node_readiness",
              return_value={"P50": 0.0, "P90": 0.0, "P99": 0.0})
@patch.object(AKSMachineClient, "_create_batch_machines")
@patch("clients.aks_machine_client.AKSClient")
def test_scale_machine_batch_partial_chunk_failure(MockAKS, mock_create_batch, _mock_wait):
    """One chunk returns []; the other chunk's names are still recorded."""
    MockAKS.return_value.subscription_id = "SUB"

    def fake(request, chunk, chunk_idx):
        if chunk_idx == 1:
            return []
        return list(chunk)

    mock_create_batch.side_effect = fake
    req = ScaleMachineRequest(
        cluster_name="cl", resource_group="rg", agentpool_name="ap",
        vm_size="Standard_D2_v3", scale_machine_count=4,
        use_batch_api=True, machine_workers=2,
    )
    c = AKSMachineClient(resource_group="rg")
    resp = c.scale_machine(req)

    expected_chunk0 = sorted([f"tmach{i:04d}" for i in range(4)])[:2]
    assert sorted(resp.successful_machines) == expected_chunk0
    assert resp.succeeded is False
    assert resp.error == ""
    assert set(resp.batch_command_execution_times.keys()) == {"chunk_0", "chunk_1"}


@patch.object(AKSMachineClient, "_wait_for_machine_node_readiness",
              return_value={"P50": 0.0, "P90": 0.0, "P99": 0.0})
@patch.object(AKSMachineClient, "_create_batch_machines")
@patch("clients.aks_machine_client.AKSClient")
def test_scale_machine_batch_worker_exception_isolated(MockAKS, mock_create_batch, _mock_wait):
    """A chunk worker raising RuntimeError must not poison the other chunk's results."""
    MockAKS.return_value.subscription_id = "SUB"

    def fake(request, chunk, chunk_idx):
        if chunk_idx == 1:
            raise RuntimeError("boom")
        return list(chunk)

    mock_create_batch.side_effect = fake
    req = ScaleMachineRequest(
        cluster_name="cl", resource_group="rg", agentpool_name="ap",
        vm_size="Standard_D2_v3", scale_machine_count=4,
        use_batch_api=True, machine_workers=2,
    )
    c = AKSMachineClient(resource_group="rg")
    resp = c.scale_machine(req)

    expected_chunk0 = sorted([f"tmach{i:04d}" for i in range(4)])[:2]
    assert sorted(resp.successful_machines) == expected_chunk0
    assert resp.succeeded is False
    assert resp.error == ""
    assert set(resp.batch_command_execution_times.keys()) == {"chunk_0", "chunk_1"}


# ---- _create_single_machine ----

@patch.object(AKSMachineClient, "_wait_for_machine_provisioning", return_value=True)
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_create_single_machine_puts_and_polls(MockAKS, mock_req, _mock_wait):
    MockAKS.return_value.subscription_id = "SUB"
    mock_req.return_value = MagicMock(status_code=202, text="")
    req = ScaleMachineRequest(
        cluster_name="cl", resource_group="rg", agentpool_name="ap",
        vm_size="Standard_D2_v3", scale_machine_count=1,
        use_batch_api=False, machine_workers=1, timeout=30,
        tags={"env": "test"},
    )
    c = AKSMachineClient(resource_group="rg")
    assert c._create_single_machine("tmach0000", req) is True
    put_call = mock_req.call_args_list[0]
    assert put_call.args[0] == "PUT"
    assert "/agentPools/ap/machines/tmach0000" in put_call.args[1]
    assert put_call.kwargs["data"]["properties"]["hardware"]["vmSize"] == "Standard_D2_v3"
    assert put_call.kwargs["data"]["tags"] == {"env": "test"}


@patch.object(AKSMachineClient, "_wait_for_machine_provisioning")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_create_single_machine_returns_false_on_bad_status(MockAKS, mock_req, mock_wait):
    MockAKS.return_value.subscription_id = "SUB"
    mock_req.return_value = MagicMock(status_code=500, text="server error")
    req = ScaleMachineRequest(
        cluster_name="cl", resource_group="rg", agentpool_name="ap",
        vm_size="Standard_D2_v3", scale_machine_count=1,
        use_batch_api=False, machine_workers=1, timeout=30,
    )
    c = AKSMachineClient(resource_group="rg")
    assert c._create_single_machine("tmach0000", req) is False
    mock_wait.assert_not_called()


# ---- _wait_for_provisioning ----

@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_provisioning_succeeded(MockAKS, mock_req, _sleep):
    mock_req.return_value = MagicMock(
        status_code=200, json=lambda: {"properties": {"provisioningState": "Succeeded"}})
    c = AKSMachineClient(resource_group="rg")
    assert c._wait_for_provisioning("https://x", timeout=30) is True


@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_provisioning_failed(MockAKS, mock_req, _sleep):
    mock_req.return_value = MagicMock(
        status_code=200, json=lambda: {"properties": {"provisioningState": "Failed"}})
    c = AKSMachineClient(resource_group="rg")
    assert c._wait_for_provisioning("https://x", timeout=30) is False


@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_provisioning_treats_persistent_none_as_failed(MockAKS, mock_req, _sleep):
    mock_req.return_value = MagicMock(status_code=200, json=lambda: {"properties": {}})
    c = AKSMachineClient(resource_group="rg")
    assert c._wait_for_provisioning("https://x", timeout=300) is False


@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_provisioning_handles_json_decode_error(MockAKS, mock_req, _sleep):
    bad = MagicMock(status_code=200)
    bad.json.side_effect = ValueError("bad json")
    good = MagicMock(
        status_code=200, json=lambda: {"properties": {"provisioningState": "Succeeded"}})
    mock_req.side_effect = [bad, good]
    c = AKSMachineClient(resource_group="rg")
    assert c._wait_for_provisioning("https://x", timeout=30) is True


@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_provisioning_logs_non_200_and_retries(MockAKS, mock_req, _sleep):
    transient = MagicMock(status_code=503)
    succ = MagicMock(
        status_code=200, json=lambda: {"properties": {"provisioningState": "Succeeded"}})
    mock_req.side_effect = [transient, succ]
    c = AKSMachineClient(resource_group="rg")
    assert c._wait_for_provisioning("https://x", timeout=30) is True


@patch("clients.aks_machine_client.time.time")
@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_wait_for_provisioning_times_out(MockAKS, mock_req, _sleep, mock_time):
    calls = {"n": 0}

    def fake_time():
        calls["n"] += 1
        if calls["n"] == 1:
            return 0
        if calls["n"] == 2:
            return 0
        return 999

    mock_time.side_effect = fake_time
    mock_req.return_value = MagicMock(
        status_code=200, json=lambda: {"properties": {"provisioningState": "Creating"}})
    c = AKSMachineClient(resource_group="rg")
    assert c._wait_for_provisioning("https://x", timeout=30) is False


# ---- _create_batch_machines ----

@patch.object(AKSMachineClient, "_make_batch_request")
@patch("clients.aks_machine_client.AKSClient")
def test_create_batch_machines_empty_chunk_short_circuits(MockAKS, mock_batch):
    MockAKS.return_value.subscription_id = "SUB"
    req = ScaleMachineRequest(
        cluster_name="cl", resource_group="rg", agentpool_name="ap",
        vm_size="Standard_D2_v3", scale_machine_count=0,
        use_batch_api=True, machine_workers=1,
    )
    c = AKSMachineClient(resource_group="rg")
    assert c._create_batch_machines(req, [], chunk_idx=0) == []
    mock_batch.assert_not_called()


@patch.object(AKSMachineClient, "_make_batch_request")
@patch("clients.aks_machine_client.AKSClient")
def test_create_batch_machines_submits_envelope(MockAKS, mock_batch):
    MockAKS.return_value.subscription_id = "SUB"
    req = ScaleMachineRequest(
        cluster_name="cl", resource_group="rg", agentpool_name="ap",
        vm_size="Standard_D2_v3", scale_machine_count=2,
        use_batch_api=True, machine_workers=1, tags={"k": "v"},
    )
    c = AKSMachineClient(resource_group="rg")
    chunk = ["m0", "m1"]
    out = c._create_batch_machines(req, chunk, chunk_idx=0)
    assert out == chunk
    args, _kwargs = mock_batch.call_args
    assert args[0] == "POST"
    assert "/machines/$batch" in args[1]
    body = args[2]
    assert [r["name"] for r in body["requests"]] == chunk
    assert all(r["httpMethod"] == "PUT" for r in body["requests"])
    assert body["requests"][0]["content"]["properties"]["hardware"]["vmSize"] == "Standard_D2_v3"
    assert body["requests"][0]["content"]["tags"] == {"k": "v"}


# ---- _make_batch_request ----

@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_make_batch_request_returns_on_2xx(MockAKS, mock_req, mock_sleep):
    mock_req.return_value = MagicMock(status_code=200)
    c = AKSMachineClient(resource_group="rg")
    c._make_batch_request("POST", "https://x", {"a": 1}, timeout=30)
    assert mock_req.call_count == 1
    args, kwargs = mock_req.call_args
    assert args[0] == "POST"
    assert args[1] == "https://x"
    assert kwargs.get("data") == {"a": 1}
    assert kwargs.get("timeout") == 30
    mock_sleep.assert_not_called()


@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_make_batch_request_raises_on_non_429_failure(MockAKS, mock_req):
    import pytest
    mock_req.return_value = MagicMock(status_code=500, text="boom")
    c = AKSMachineClient(resource_group="rg")
    with pytest.raises(RuntimeError, match="batch request failed: 500"):
        c._make_batch_request("POST", "https://x", {"a": 1}, timeout=30)


@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_make_batch_request_retries_on_429_then_succeeds(MockAKS, mock_req, _sleep):
    mock_req.side_effect = [
        MagicMock(status_code=429, text="throttled"),
        MagicMock(status_code=429, text="throttled"),
        MagicMock(status_code=200, text=""),
    ]
    c = AKSMachineClient(resource_group="rg")
    c._make_batch_request("POST", "https://x", {"a": 1}, timeout=30)
    assert mock_req.call_count == 3


@patch("clients.aks_machine_client.time.sleep")
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_make_batch_request_raises_after_429_retry_exhaustion(MockAKS, mock_req, _sleep):
    import pytest
    mock_req.return_value = MagicMock(status_code=429, text="throttled")
    c = AKSMachineClient(resource_group="rg")
    with pytest.raises(RuntimeError, match="exceeded .* 429 retries"):
        c._make_batch_request("POST", "https://x", {"a": 1}, timeout=30)


# ---- get_cluster_name / get_cluster_data passthroughs ----

@patch("clients.aks_machine_client.AKSClient")
def test_get_cluster_name_passthrough(MockAKS):
    MockAKS.return_value.get_cluster_name.return_value = "cl1"
    c = AKSMachineClient(resource_group="rg")
    assert c.get_cluster_name() == "cl1"


@patch("clients.aks_machine_client.AKSClient")
def test_get_cluster_data_passthrough(MockAKS):
    MockAKS.return_value.get_cluster_data.return_value = {"id": "x"}
    c = AKSMachineClient(resource_group="rg")
    assert c.get_cluster_data("cl1") == {"id": "x"}


# ---- scale_machine cloud_data attach failure path ----

@patch.object(AKSMachineClient, "get_cluster_data", side_effect=RuntimeError("snap fail"))
@patch.object(AKSMachineClient, "_wait_for_machine_node_readiness",
              return_value={"P50": 0.0, "P90": 0.0, "P99": 0.0})
@patch.object(AKSMachineClient, "_create_single_machine", return_value=True)
@patch("clients.aks_machine_client.AKSClient")
def test_scale_machine_cloud_data_failure_swallowed(MockAKS, _mock_single, _mock_wait, _mock_cd):
    MockAKS.return_value.subscription_id = "SUB"
    req = ScaleMachineRequest(
        cluster_name="cl", resource_group="rg", agentpool_name="ap",
        vm_size="Standard_D2_v3", scale_machine_count=1,
        use_batch_api=False, machine_workers=1,
    )
    c = AKSMachineClient(resource_group="rg")
    resp = c.scale_machine(req)
    assert resp.succeeded is True
    assert resp.cloud_data is None


# ---- create_machine_agentpool: rg mismatch warning path ----

@patch.object(AKSMachineClient, "_wait_for_agentpool_provisioning", return_value=True)
@patch.object(AKSMachineClient, "make_request")
@patch("clients.aks_machine_client.AKSClient")
def test_create_machine_agentpool_logs_when_rg_mismatches(MockAKS, mock_req, _mock_wait, caplog):
    MockAKS.return_value.subscription_id = "SUB"
    MockAKS.return_value.resource_group = "rg-bound"
    mock_req.return_value = MagicMock(status_code=201, text="")
    c = AKSMachineClient(resource_group="rg-bound")
    with caplog.at_level("WARNING", logger="clients.aks_machine_client"):
        ok = c.create_machine_agentpool("apool", "cl", "rg-other", timeout=30)
    assert ok is True
    assert any(
        "rg-other" in r.getMessage() and "rg-bound" in r.getMessage()
        for r in caplog.records
    ), f"expected RG-mismatch warning, got: {[r.getMessage() for r in caplog.records]}"


# ---- _array_split edge cases ----

def test_array_split_empty_returns_empty():
    assert AKSMachineClient._array_split([], 3) == []


def test_array_split_clamps_workers_to_len():
    out = AKSMachineClient._array_split(["a", "b"], 4)
    assert len(out) == 2  # workers clamped to len(items)
    assert all(len(c) == 1 for c in out)
    assert sorted(c[0] for c in out) == ["a", "b"]
