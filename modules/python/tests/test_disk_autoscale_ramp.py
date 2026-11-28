import json
from types import SimpleNamespace as Obj
from unittest.mock import patch

import pytest
from kubernetes.client import ApiClient
from kubernetes.client.exceptions import ApiException

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


@pytest.fixture(name="overpacking")
def overpacked_cluster():
    kube = cluster(disks_per_node=4)
    workload_node = node()
    workload_node.metadata.uid = "node-uid"
    pods = [pod(index, 4) for index in range(6)]
    for item in pods:
        item.metadata.resource_version = "10"
        item.metadata.deletion_timestamp = None
    for item in pods[4:]:
        item.spec.node_name = "node-0"
        item.status.phase = "Pending"
        item.status.conditions = []
    kube.get_nodes.side_effect = None
    kube.get_nodes.return_value = [workload_node]
    kube.api.list_namespaced_pod.side_effect = None
    kube.api.list_namespaced_pod.return_value = Obj(items=pods)
    kube.api.read_namespaced_pod.side_effect = lambda name, _: next(
        item for item in pods if item.metadata.name == name
    )
    recovery = {"next_check": 0, "pending": {}, "attempts": {}}
    report = {"overpacking_recovery": {
        "deletions": [], "attempts_by_pod": recovery["attempts"],
    }}

    def check():
        disk.recover_overpacked_pods(
            kube, "test", "cas=dedicated", [workload_node], pods, 4, recovery, report,
        )

    return Obj(
        kube=kube, node=workload_node, pods=pods, recovery=recovery, report=report,
        check=check,
    )


def test_recovery_checks_every_minute_and_waits_two_minutes(overpacking, ramp_clock):
    case = overpacking
    for instant in (0, 5, 59, 60, 119):
        ramp_clock.now = instant
        case.check()
        case.kube.api.delete_namespaced_pod.assert_not_called()
    assert case.kube.storage.read_csi_node.call_count == 2
    ramp_clock.now = 120
    case.check()
    assert case.kube.api.delete_namespaced_pod.call_count == 2
    for call, item in zip(case.kube.api.delete_namespaced_pod.call_args_list, case.pods[4:]):
        assert call.args == (item.metadata.name, "test")
        assert ApiClient().sanitize_for_serialization(call.kwargs["body"]) == {
            "preconditions": {"uid": item.metadata.uid, "resourceVersion": "10"},
        }
    assert case.recovery["attempts"] == {"disk-workload-4": 1, "disk-workload-5": 1}
    assert all(entry["result"] == "deleted"
               for entry in case.report["overpacking_recovery"]["deletions"])
    assert not case.recovery["pending"]
    case.kube.api.delete_namespaced_persistent_volume_claim.assert_not_called()
    case.kube.api.delete_persistent_volume.assert_not_called()


@pytest.mark.parametrize("condition", [
    "unready-node", "cordoned-node", "unfilled-slots", "running-excess",
    "unscheduled", "terminating", "no-overpacking",
])
def test_recovery_ignores_normal_startup_and_non_candidates(
        overpacking, ramp_clock, condition):
    case = overpacking
    if condition == "unready-node":
        case.node.status.conditions[0].status = "False"
    elif condition == "cordoned-node":
        case.node.spec.unschedulable = True
    elif condition == "unfilled-slots":
        case.pods[0].status.phase = "Pending"
    elif condition == "running-excess":
        for item in case.pods:
            item.status.phase = "Running"
    elif condition == "unscheduled":
        for item in case.pods[4:]:
            item.spec.node_name = None
    elif condition == "terminating":
        for item in case.pods[4:]:
            item.metadata.deletion_timestamp = "terminating"
    elif condition == "no-overpacking":
        del case.pods[4:]
    for instant in (0, 60, 120, 180):
        ramp_clock.now = instant
        case.check()
    case.kube.api.delete_namespaced_pod.assert_not_called()
    case.kube.storage.read_csi_node.assert_not_called()
    assert not case.recovery["pending"]


@pytest.mark.parametrize("change", ["pod-uid", "node-uid", "pending-interruption"])
def test_recovery_restarts_grace_after_identity_or_state_changes(
        overpacking, ramp_clock, change):
    case = overpacking
    case.pods.pop()
    case.check()
    ramp_clock.now = 60
    case.check()
    ramp_clock.now = 65
    if change == "pod-uid":
        case.pods[4].metadata.uid = "replacement"
    elif change == "node-uid":
        case.node.metadata.uid = "replacement-node"
    else:
        case.pods[4].spec.node_name = None
    case.check()
    assert not case.recovery["pending"]
    case.pods[4].spec.node_name = "node-0"
    for instant in (120, 180, 239):
        ramp_clock.now = instant
        case.check()
        case.kube.api.delete_namespaced_pod.assert_not_called()
    ramp_clock.now = 240
    case.check()
    case.kube.api.delete_namespaced_pod.assert_called_once()


def test_recovery_requires_live_limit_on_detection_and_recheck(overpacking, ramp_clock):
    case = overpacking
    case.pods.pop()
    csi = case.kube.storage.read_csi_node.return_value
    csi.spec.drivers[0].allocatable.count = 8
    case.check()
    assert not case.recovery["pending"]
    csi.spec.drivers[0].allocatable.count = 4
    for instant in (60, 120):
        ramp_clock.now = instant
        case.check()
    case.kube.storage.read_csi_node.side_effect = [
        csi, Obj(spec=Obj(drivers=[Obj(name=disk.DRIVER, allocatable=Obj(count=8))])),
    ]
    ramp_clock.now = 180
    case.check()
    case.kube.api.delete_namespaced_pod.assert_not_called()
    assert not case.recovery["pending"]


@pytest.mark.parametrize("change", ["node-not-ready", "pod-replaced", "slots-not-full"])
def test_recovery_refreshes_node_and_placement_before_deletion(
        overpacking, ramp_clock, change):
    case = overpacking
    case.pods.pop()
    for instant in (0, 60):
        ramp_clock.now = instant
        case.check()

    def refresh(**_kwargs):
        if change == "node-not-ready":
            case.node.status.conditions[0].status = "False"
        elif change == "pod-replaced":
            case.pods[4].metadata.uid = "replacement"
        else:
            case.pods[0].status.phase = "Pending"
        return [case.node]

    case.kube.get_nodes.side_effect = refresh
    ramp_clock.now = 120
    case.check()
    case.kube.api.read_namespaced_pod.assert_not_called()
    case.kube.api.delete_namespaced_pod.assert_not_called()
    assert not case.recovery["pending"]


def test_recovery_rejects_missing_resource_version(overpacking, ramp_clock):
    case = overpacking
    case.pods.pop()
    case.pods[4].metadata.resource_version = None
    for instant in (0, 60):
        ramp_clock.now = instant
        case.check()
    ramp_clock.now = 120
    with pytest.raises(ValueError, match="Cannot safely recover.*resourceVersion"):
        case.check()
    case.kube.api.delete_namespaced_pod.assert_not_called()


@pytest.mark.parametrize("change", ["ready", "replacement", "terminating", "unassigned"])
def test_recovery_rechecks_pod_immediately_before_deletion(
        overpacking, ramp_clock, change):
    case = overpacking
    case.pods.pop()
    for instant in (0, 60):
        ramp_clock.now = instant
        case.check()

    def read(name, namespace):
        assert (name, namespace) == ("disk-workload-4", "test")
        item = case.pods[4]
        if change == "ready":
            item.status.phase = "Running"
        elif change == "replacement":
            item.metadata.uid = "replacement"
        elif change == "terminating":
            item.metadata.deletion_timestamp = "terminating"
        else:
            item.spec.node_name = None
        return item

    case.kube.api.read_namespaced_pod.side_effect = read
    ramp_clock.now = 120
    case.check()
    case.kube.api.delete_namespaced_pod.assert_not_called()
    assert not case.recovery["attempts"]


@pytest.mark.parametrize("status", [404, 409, 403, 422, 500])
@pytest.mark.parametrize("operation", ["read", "delete"])
def test_recovery_handles_only_expected_concurrency_errors(
        overpacking, ramp_clock, status, operation):
    case = overpacking
    case.pods.pop()
    for instant in (0, 60):
        ramp_clock.now = instant
        case.check()
    api = (case.kube.api.read_namespaced_pod if operation == "read"
           else case.kube.api.delete_namespaced_pod)
    api.side_effect = ApiException(status=status)
    ramp_clock.now = 120
    if status in (404, 409):
        case.check()
        assert not case.recovery["pending"]
    else:
        with pytest.raises(ApiException) as error:
            case.check()
        assert error.value.status == status
    assert not case.recovery["attempts"]
    entries = case.report["overpacking_recovery"]["deletions"]
    if operation == "delete":
        assert entries[-1]["result"] == ("skipped" if status in (404, 409) else "failure")
        assert entries[-1]["status"] == status


def test_recovery_conflict_retries_after_new_grace_without_consuming_attempt(
        overpacking, ramp_clock):
    case = overpacking
    case.pods.pop()
    case.kube.api.delete_namespaced_pod.side_effect = [ApiException(status=409), None]
    for instant in (0, 60, 120, 180, 240, 300):
        ramp_clock.now = instant
        case.check()
    assert case.kube.api.delete_namespaced_pod.call_count == 2
    assert case.recovery["attempts"] == {"disk-workload-4": 1}
    entries = case.report["overpacking_recovery"]["deletions"]
    assert [entry["result"] for entry in entries] == ["skipped", "deleted"]
    assert [entry["attempt"] for entry in entries] == [1, 1]


def test_recovery_retries_replacements_but_stops_after_three_deletions(
        overpacking, ramp_clock):
    case = overpacking
    case.pods.pop()

    def replace(*_args, **_kwargs):
        case.pods[4].metadata.uid = f"replacement-{ramp_clock.now}"

    case.kube.api.delete_namespaced_pod.side_effect = replace
    for instant in range(0, 661, 60):
        ramp_clock.now = instant
        if instant == 660:
            with pytest.raises(ValueError, match="recovery exhausted.*3 deletions"):
                case.check()
        else:
            case.check()
    assert case.kube.api.delete_namespaced_pod.call_count == 3
    assert case.recovery["attempts"] == {"disk-workload-4": 3}
    assert [entry["attempt"] for entry in case.report["overpacking_recovery"]["deletions"]] == [
        1, 2, 3,
    ]


@patch.object(disk, "cleanup", return_value={})
@pytest.mark.parametrize("node_count", [2, 20])
def test_timed_ramp_recovers_repeated_overpacking_during_final_wait(
        _cleanup, tmp_path, ramp_clock, node_count):
    kube = cluster(disks_per_node=4)
    list_pods = kube.api.list_namespaced_pod.side_effect
    list_nodes = kube.get_nodes.side_effect
    recovered = {}
    deletion_times = []

    def pods(*args, **kwargs):
        result = list_pods(*args, **kwargs)
        for item in result.items:
            item.metadata.deletion_timestamp = None
            item.metadata.resource_version = "10"
            attempts = recovered.get(item.metadata.name, 0)
            if attempts:
                item.metadata.uid = f"{item.metadata.name}-v{attempts}"
            if item.metadata.name == "disk-workload-7" and attempts < 2:
                item.spec.node_name = "node-0"
                item.status.phase = "Pending"
                item.status.conditions = []
        return result

    def nodes(**kwargs):
        result = list_nodes(**kwargs)
        for item in result:
            item.metadata.uid = f"{item.metadata.name}-uid"
        return result

    def delete(name, namespace, **_kwargs):
        assert namespace.startswith("autoscale-disk-")
        deletion_times.append(ramp_clock.now)
        recovered[name] = recovered.get(name, 0) + 1

    kube.get_nodes.side_effect = nodes
    kube.api.list_namespaced_pod.side_effect = pods
    kube.api.read_namespaced_pod.side_effect = lambda name, ns: next(
        item for item in pods(ns).items if item.metadata.name == name
    )
    kube.api.delete_namespaced_pod.side_effect = delete
    path = tmp_path / "report.json"
    report = disk.execute(
        kube, node_count, "cas=dedicated", "managed-csi", 600, 30, 1, path,
        batch_interval=1200,
    )
    assert report["result"] == "success"
    assert deletion_times == [120, 300]
    assert report["overpacking_recovery"]["attempts_by_pod"] == {"disk-workload-7": 2}
    assert report["overpacking_recovery"]["check_interval_seconds"] == 60
    assert report["overpacking_recovery"]["grace_period_seconds"] == 120
    assert report["overpacking_recovery"]["max_attempts_per_pod"] == 3
    sample = report["stages"][1]["pod_readiness_samples"]["disk-workload-7"]
    assert sample == {"pod_uid": "disk-workload-7-v2", "e2e_ready_seconds": 305}
    assert report["ramp_all_pods_storage_ready_seconds"] == (305 if node_count == 2 else 1200)
    assert report["final_pods_per_node"] == {
        f"node-{index}": 4 for index in range(node_count)
    }
    assert json.loads(path.read_text()) == report
    manifest = kube.app.create_namespaced_stateful_set.call_args.args[1]
    assert manifest["spec"]["persistentVolumeClaimRetentionPolicy"] == {
        "whenDeleted": "Retain", "whenScaled": "Retain",
    }
    assert [call.args[2]["spec"]["replicas"]
            for call in kube.app.patch_namespaced_stateful_set_scale.call_args_list] == (
                [1, 8] if node_count == 2 else [1, 61, 80]
            )
    if node_count == 20:
        assert report["stages"][2]["pod_readiness_samples"]["disk-workload-61"][
            "e2e_ready_seconds"
        ] == 0
        assert report["stages"][2]["timings"]["nodes"] == {}
    _cleanup.assert_called_once()


@patch.object(disk, "cleanup", return_value={})
def test_timed_ramp_recovery_failure_is_reported_and_cleaned_up(
        _cleanup, tmp_path, ramp_clock):
    kube = cluster(disks_per_node=4)
    list_pods = kube.api.list_namespaced_pod.side_effect
    list_nodes = kube.get_nodes.side_effect
    replacements = {}

    def pods(*args, **kwargs):
        result = list_pods(*args, **kwargs)
        for item in result.items:
            item.metadata.deletion_timestamp = None
            item.metadata.resource_version = "10"
            attempts = replacements.get(item.metadata.name, 0)
            if attempts:
                item.metadata.uid = f"{item.metadata.name}-v{attempts}"
            if item.metadata.name == "disk-workload-7":
                item.spec.node_name = "node-0"
                item.status.phase = "Pending"
                item.status.conditions = []
        return result

    def nodes(**kwargs):
        result = list_nodes(**kwargs)
        for item in result:
            item.metadata.uid = item.metadata.name
        return result

    def delete(name, _namespace, **_kwargs):
        replacements[name] = replacements.get(name, 0) + 1

    kube.get_nodes.side_effect = nodes
    kube.api.list_namespaced_pod.side_effect = pods
    kube.api.read_namespaced_pod.side_effect = lambda name, ns: next(
        item for item in pods(ns).items if item.metadata.name == name
    )
    kube.api.delete_namespaced_pod.side_effect = delete
    path = tmp_path / "report.json"
    with pytest.raises(ValueError, match="Overpacking recovery exhausted"):
        disk.execute(
            kube, 2, "cas=dedicated", "managed-csi", 900, 30, 1, path,
            batch_interval=1200,
        )
    report = json.loads(path.read_text())
    assert ramp_clock.now == 660
    assert report["result"] == "failure"
    assert "3 deletions" in report["error"]
    assert report["overpacking_recovery"]["attempts_by_pod"] == {"disk-workload-7": 3}
    assert not report["pod_readiness_e2e_seconds"]["complete"]
    assert (tmp_path / "pod-readiness.csv").exists()
    _cleanup.assert_called_once()
