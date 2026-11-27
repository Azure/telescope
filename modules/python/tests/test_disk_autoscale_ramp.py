import json
from types import SimpleNamespace as Obj
from unittest.mock import patch

import pytest

from clusterloader2.autoscale import disk_autoscale as disk
from tests.test_disk_autoscale import cluster, node, pod


@pytest.fixture(name="ramp_clock")
def simulated_clock(monkeypatch):
    clock = Obj(now=0)
    monkeypatch.setattr(disk.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(disk.random, "randint", lambda *_: 60)

    def sleep(seconds):
        assert seconds > 0
        clock.now += seconds

    monkeypatch.setattr(disk.time, "sleep", sleep)
    return clock


@patch.object(disk, "cleanup", return_value={})
@pytest.mark.parametrize("mode", ["ready", "pending", "replacement"])
def test_timed_ramp_submits_every_20_minutes(_cleanup, tmp_path, ramp_clock, mode):
    kube = cluster(disks_per_node=4)
    scale = kube.app.patch_namespaced_stateful_set_scale.side_effect
    requests = []

    def request(name, namespace, body):
        requests.append((ramp_clock.now, body["spec"]["replicas"]))
        scale(name, namespace, body)

    kube.app.patch_namespaced_stateful_set_scale.side_effect = request
    list_pods = kube.api.list_namespaced_pod.side_effect

    def pods(*args, **kwargs):
        result = list_pods(*args, **kwargs)
        if mode == "pending" and ramp_clock.now < 1205:
            for item in result.items[1:]:
                item.status.phase = "Pending"
                item.status.conditions = []
                item.spec.node_name = None
        if mode == "replacement" and ramp_clock.now >= 1200:
            result.items[1].metadata.uid = "replacement"
            if ramp_clock.now < 1205:
                result.items[1].status.phase = "Pending"
                result.items[1].status.conditions = []
        return result

    kube.api.list_namespaced_pod.side_effect = pods
    path = tmp_path / "report.json"
    report = disk.execute(
        kube, 20, "cas=dedicated", "managed-csi", 30, 30, 1, path,
        batch_interval=1200,
    )
    assert requests == [(0, 1), (0, 61), (1200, 80)]
    assert report["result"] == "success"
    assert report["batch_interval_seconds"] == 1200
    assert report["pod_readiness_e2e_seconds"]["complete"]
    assert sum(report["final_pods_per_node"].values()) == 80
    assert len(report["node_timings"]) == 20
    assert len(report["pod_timings"]) == 80
    assert report["stages"][1]["pod_readiness_samples"]["disk-workload-1"][
        "e2e_ready_seconds"
    ] == (0 if mode == "ready" else 1205)
    assert report["stages"][2]["pod_readiness_samples"]["disk-workload-61"][
        "e2e_ready_seconds"
    ] == (5 if mode == "pending" else 0)
    first_pod = next(row for row in report["pod_timings"]
                     if row["pod_name"] == "disk-workload-1")
    assert first_pod["e2e_ready_seconds"] == (0 if mode == "ready" else 1205)
    if mode == "replacement":
        assert first_pod["pod_uid"] == "replacement"
    assert json.loads(path.read_text()) == report
    assert (tmp_path / "pod-readiness.csv").exists()
    _cleanup.assert_called_once()


@patch.object(disk, "cleanup", return_value={})
@pytest.mark.parametrize("failure", ["pending", "evidence", "disks", "limit", "extra-nodes"])
def test_timed_ramp_failure_exports_and_cleans_up(
        _cleanup, tmp_path, ramp_clock, failure):
    kube = cluster(disks_per_node=4)
    list_pods = kube.api.list_namespaced_pod.side_effect

    def pods(*args, **kwargs):
        result = list_pods(*args, **kwargs)
        if len(result.items) > 1:
            if failure == "pending":
                result.items[-1].status.phase = "Pending"
            elif failure == "disks":
                result.items[-1].spec.volumes = []
        return result

    kube.api.list_namespaced_pod.side_effect = pods
    if failure == "evidence":
        events = kube.api.list_namespaced_event.side_effect
        kube.api.list_namespaced_event.side_effect = (
            lambda ns, **kw: events(ns, **kw) if kw else Obj(items=[])
        )
    if failure == "limit":
        read_limit = kube.storage.read_csi_node.return_value
        kube.storage.read_csi_node.side_effect = (
            lambda name: read_limit if name == "node-0" else Obj(
                spec=Obj(drivers=[Obj(name=disk.DRIVER, allocatable=Obj(count=8))])
            )
        )
    if failure == "extra-nodes":
        get_nodes = kube.get_nodes.side_effect

        def nodes(**kwargs):
            result = get_nodes(**kwargs)
            return result + [node("unexpected")] if len(result) > 1 else result

        kube.get_nodes.side_effect = nodes
    path = tmp_path / "report.json"
    with pytest.raises((TimeoutError, ValueError)):
        disk.execute(kube, 20, "cas=dedicated", "managed-csi", 10, 30, 1,
                     path, batch_interval=900)
    report = json.loads(path.read_text())
    assert report["result"] == "failure"
    assert report["error"]
    assert (tmp_path / "pod-readiness.csv").exists()
    if failure in ("pending", "evidence"):
        assert ramp_clock.now == 910
        assert report["stages"][-1]["replicas"] == 80
    if failure == "pending":
        assert not report["pod_readiness_e2e_seconds"]["complete"]
    _cleanup.assert_called_once()


@patch.object(disk, "execute")
@patch.object(disk, "KubernetesClient")
def test_cli_batch_interval(_client, execute, monkeypatch):
    monkeypatch.setattr("sys.argv", [
        "disk_autoscale", "execute", "--report-file", "report.json",
        "--batch-interval-seconds", "900",
    ])
    disk.main()
    assert execute.call_args.kwargs == {"batch_interval": 900}


def test_execute_rejects_negative_batch_interval(tmp_path):
    kube = cluster()
    path = tmp_path / "report.json"
    with pytest.raises(ValueError, match="Batch interval must be nonnegative"):
        disk.execute(kube, 20, "cas=dedicated", "managed-csi", 30, 30, 1, path,
                     batch_interval=-1)
    kube.api.create_namespace.assert_not_called()
    assert json.loads(path.read_text())["result"] == "failure"


@patch.object(disk.logger, "info")
def test_node_progress_counts_and_logging_cadence(info):
    ready = node()
    unready = node("node-1")
    unready.status.conditions[0].status = "False"
    cordoned = node("node-2")
    cordoned.spec.unschedulable = True
    nodes = [ready, unready, cordoned]
    progress = disk.log_workload_progress(nodes, 20, [], 80, 0)
    info.assert_called_once_with(
        "Workload nodes: ready=%s, observed=%s, target=%s; "
        "pods: ready=%s, observed=%s, target=%s; elapsed=%.0fs",
        1, 3, 20, 0, 0, 80, 0,
    )
    progress = disk.log_workload_progress(nodes, 20, [], 80, 59, progress)
    assert info.call_count == 1
    progress = disk.log_workload_progress(nodes, 20, [], 80, 60, progress)
    assert info.call_count == 2
    unready.status.conditions[0].status = "True"
    progress = disk.log_workload_progress(nodes, 20, [], 80, 61, progress)
    assert info.call_args.args[1:] == (2, 3, 20, 0, 0, 80, 61)
    progress = disk.log_workload_progress(nodes, 30, [], 80, 62, progress)
    assert info.call_args.args[1:] == (2, 3, 30, 0, 0, 80, 62)
    disk.log_workload_progress(nodes[:2], 30, [], 80, 63, progress)
    assert info.call_args.args[1:] == (2, 2, 30, 0, 0, 80, 63)


@patch.object(disk.logger, "info")
def test_pod_progress_counts_current_running_and_ready_pods(info):
    pods = [pod(index) for index in range(4)]
    pods[1].status.conditions[0].status = "False"
    pods[2].status.phase = "Pending"
    pods[3].status.phase = "Succeeded"
    progress = disk.log_workload_progress([node()], 2, pods, 8, 0)
    assert info.call_args.args[1:] == (1, 1, 2, 1, 4, 8, 0)
    progress = disk.log_workload_progress([node()], 2, pods, 8, 5, progress)
    assert info.call_count == 1
    pods[1].status.conditions[0].status = "True"
    progress = disk.log_workload_progress([node()], 2, pods, 8, 10, progress)
    assert info.call_args.args[1:] == (1, 1, 2, 2, 4, 8, 10)
    pods[0].status.conditions[0].status = "False"
    progress = disk.log_workload_progress([node()], 2, pods, 8, 15, progress)
    assert info.call_args.args[1:] == (1, 1, 2, 1, 4, 8, 15)
    progress = disk.log_workload_progress([node()], 2, pods[:3], 8, 20, progress)
    assert info.call_args.args[1:] == (1, 1, 2, 1, 3, 8, 20)
    disk.log_workload_progress([node()], 2, pods[:3], 7, 25, progress)
    assert info.call_args.args[1:] == (1, 1, 2, 1, 3, 7, 25)


@patch.object(disk, "cleanup", return_value={})
@patch.object(disk.logger, "info")
@pytest.mark.parametrize("batch_interval", [0, 900])
@pytest.mark.usefixtures("ramp_clock")
def test_execution_logs_bootstrap_and_final_node_readiness(
        info, _cleanup, tmp_path, batch_interval):
    disk.execute(
        cluster(disks_per_node=4), 2, "cas=dedicated", "managed-csi", 30, 30, 1,
        tmp_path / "report.json", batch_interval=batch_interval,
    )
    progress = [call.args[1:] for call in info.call_args_list
                if call.args[0].startswith("Workload nodes:")]
    assert progress[0][:3] == (1, 1, 1)
    assert progress[-1][:3] == (2, 2, 2)
    assert progress[0][3:6] == (1, 1, 1)
    assert progress[-1][3:6] == (8, 8, 8)
