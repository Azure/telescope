import json
import csv
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as Obj
from unittest.mock import MagicMock, patch

import pytest

from clusterloader2.autoscale import disk_autoscale as disk


@pytest.fixture(autouse=True)
def fixed_batch_size():
    with patch.object(disk.random, "randint", return_value=5) as batch_size:
        yield batch_size


def node(name="node-0"):
    return Obj(metadata=Obj(name=name), spec=Obj(unschedulable=False),
               status=Obj(conditions=[Obj(type="Ready", status="True")]))


def pod(index, limit=8):
    name = f"{disk.WORKLOAD}-{index}"
    return Obj(
        metadata=Obj(name=name, uid=name),
        spec=Obj(node_name=f"node-{index // limit}", volumes=[
            Obj(persistent_volume_claim=Obj(claim_name=f"data-{index}"))
        ]),
        status=Obj(phase="Running", conditions=[Obj(type="Ready", status="True")]),
    )


def event(reason, message, uid="disk-workload-8"):
    return Obj(reason=reason, message=message, involved_object=Obj(uid=uid))


def volume(index, namespace="test"):
    return Obj(
        metadata=Obj(name=f"pv-{index}"),
        spec=Obj(claim_ref=Obj(namespace=namespace),
                 csi=Obj(driver=disk.DRIVER, volume_handle=f"disk-{index}")),
    )


def attachment(index, limit=8):
    return Obj(
        spec=Obj(attacher=disk.DRIVER, node_name=f"node-{index // limit}",
                 source=Obj(persistent_volume_name=f"pv-{index}")),
        status=Obj(attached=True),
    )


def cluster(disks_per_node=8):
    kube = MagicMock()
    state = {"replicas": 0}
    kube.get_nodes.side_effect = lambda **_: [
        node(f"node-{index}") for index in range(
            (state["replicas"] + disks_per_node - 1) // disks_per_node
        )
    ]
    kube.get_ready_nodes.side_effect = kube.get_nodes.side_effect
    kube.storage.read_csi_node.return_value = Obj(spec=Obj(drivers=[
        Obj(name=disk.DRIVER, allocatable=Obj(count=disks_per_node))
    ]))
    kube.storage.read_storage_class.return_value = Obj(
        provisioner=disk.DRIVER, reclaim_policy="Delete",
        volume_binding_mode="WaitForFirstConsumer",
    )
    kube.api.list_namespaced_pod.side_effect = lambda *_args, **_kwargs: Obj(
        items=[pod(index, disks_per_node) for index in range(state["replicas"])]
    )
    kube.api.list_namespaced_persistent_volume_claim.side_effect = lambda _: Obj(items=[
        Obj(metadata=Obj(name=f"data-{index}"), status=Obj(phase="Bound"),
            spec=Obj(volume_name=f"pv-{index}"))
        for index in range(state["replicas"])
    ])
    kube.api.read_persistent_volume.side_effect = lambda name: volume(int(name.split("-")[1]))
    kube.storage.list_volume_attachment.side_effect = lambda: Obj(
        items=[attachment(index, disks_per_node) for index in range(state["replicas"])]
    )

    def scale(_name, _namespace, body):
        state["replicas"] = body["spec"]["replicas"]

    def events(_namespace, field_selector):
        uid = field_selector.split("=", 1)[1]
        count = (state["replicas"] - 1) // disks_per_node
        message = (
            f"{count} node(s) exceed max volume count"
            if count else "5 node(s) didn't match Pod's node affinity/selector"
        )
        return Obj(items=[
            event("FailedScheduling", message, uid),
            event("TriggeredScaleUp", "pod triggered scale-up: csipool1", uid),
        ])

    kube.app.patch_namespaced_stateful_set_scale.side_effect = scale
    kube.api.list_namespaced_event.side_effect = events
    return kube


@pytest.mark.parametrize("batch_size", [5, 30])
def test_ten_node_stage_targets(batch_size, fixed_batch_size):
    fixed_batch_size.return_value = batch_size
    targets = list(disk.stage_targets(10, 8))
    previous_replicas, previous_nodes = 1, 1
    for nodes, replicas, overflow in targets:
        assert replicas == min(80, previous_replicas + batch_size)
        assert nodes == (replicas + 7) // 8
        assert overflow == (nodes > previous_nodes)
        previous_replicas, previous_nodes = replicas, nodes
    assert targets[-1][:2] == (10, 80)
    assert all(call.args == (5, 30) for call in fixed_batch_size.call_args_list)


def test_stage_targets_draws_a_new_random_increment_each_batch(fixed_batch_size):
    fixed_batch_size.side_effect = [5, 30, 12, 30, 5]
    assert list(disk.stage_targets(10, 8)) == [
        (1, 6, False), (5, 36, True), (6, 48, True),
        (10, 78, True), (10, 80, False),
    ]
    assert fixed_batch_size.call_count == 5


@pytest.mark.parametrize("nodes,limit", [(1, 8), (11, 8), (10, 0)])
def test_reject_unsafe_targets(nodes, limit):
    with pytest.raises(ValueError):
        list(disk.stage_targets(nodes, limit))


@pytest.mark.parametrize("drivers", [
    [], [Obj(name=disk.DRIVER, allocatable=None)],
    [Obj(name=disk.DRIVER, allocatable=Obj(count=0))],
])
def test_requires_live_csi_limit(drivers):
    kube = MagicMock()
    kube.storage.read_csi_node.return_value = Obj(spec=Obj(drivers=drivers))
    with pytest.raises(ValueError, match="positive"):
        disk.disk_limit(kube, "node-0")


def test_evidence_requires_disk_limit_and_autoscaler_for_same_pod():
    events = [
        event("FailedScheduling", "1 node(s) exceed max volume count"),
        event("TriggeredScaleUp", "scale", uid="stale-pod"),
    ]
    assert disk.scale_up_evidence(events, "disk-workload-8", 1) is None
    events.append(event("TriggeredScaleUp", "scale"))
    assert disk.scale_up_evidence(events, "disk-workload-8", 1)
    assert disk.scale_up_evidence(events, "disk-workload-8", 2)
    events[0].message = "0 node(s) exceed max volume count"
    assert disk.scale_up_evidence(events, "disk-workload-8", 1) is None
    events[0].message = "1 Insufficient cpu"
    assert disk.scale_up_evidence(events, "disk-workload-8", 1) is None


def test_bootstrap_requires_scheduling_and_scale_up_events_for_first_pod():
    events = [
        event("FailedScheduling", "5 node(s) didn't match Pod's node affinity/selector",
              uid="disk-workload-0"),
    ]
    assert disk.scale_up_evidence(events, "disk-workload-0", 0) is None
    events.append(event("TriggeredScaleUp", "0->1", uid="other-pod"))
    assert disk.scale_up_evidence(events, "disk-workload-0", 0) is None
    events.append(event("TriggeredScaleUp", "0->1", uid="disk-workload-0"))
    assert disk.scale_up_evidence(events, "disk-workload-0", 0)
    assert disk.scale_up_evidence(events, "disk-workload-0", 1) is None


@patch.object(disk.time, "sleep")
def test_bootstrap_waits_for_first_node_and_pending_pod(sleep):
    kube = cluster()
    assert kube.get_nodes(label_selector="cas=dedicated") == []
    kube.app.patch_namespaced_stateful_set_scale(
        disk.WORKLOAD, "test", {"spec": {"replicas": 1}}
    )
    pending = pod(0)
    pending.spec.node_name = None
    pending.status.phase = "Pending"
    pending.status.conditions = []
    kube.get_nodes.side_effect = [[], [node()]]
    kube.api.list_namespaced_pod.side_effect = [
        Obj(items=[pending]), Obj(items=[pod(0)]),
    ]
    stage, nodes = disk.wait_for_stage(
        kube, "test", "cas=dedicated", 1, 1, None, set(), True, 30
    )
    assert stage["phase"] == "bootstrap"
    assert stage["disks_per_node"] == 8
    assert nodes == {"node-0"}
    assert stage["pods_per_node"] == {"node-0": 1}
    sleep.assert_called_once_with(5)


def test_bootstrap_cannot_pass_without_autoscaler_evidence():
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(
        disk.WORKLOAD, "test", {"spec": {"replicas": 1}}
    )
    kube.api.list_namespaced_event.side_effect = None
    kube.api.list_namespaced_event.return_value = Obj(items=[
        event("FailedScheduling", "No matching nodes", uid="disk-workload-0"),
    ])
    with pytest.raises(TimeoutError, match="evidence=None"):
        disk.wait_for_stage(kube, "test", "cas=dedicated", 1, 1, None,
                            set(), True, 0)


@patch.object(disk, "cleanup", return_value={})
def test_bootstrap_uses_actual_disk_limit_for_later_batches(_cleanup, tmp_path):
    kube = cluster(disks_per_node=4)
    report = disk.execute(
        kube, 10, "cas=dedicated", "managed-csi", 30, 30, 1, tmp_path / "report.json"
    )
    assert report["disks_per_node"] == 4
    assert report["pod_count"] == 40
    assert [stage["replicas"] for stage in report["stages"][:5]] == [1, 6, 11, 16, 21]
    assert report["stages"][1]["node_count"] == 2
    assert set(report["stages"][-1]["pods_per_node"].values()) == {4}


@patch.object(disk, "cleanup")
@pytest.mark.parametrize("batch_size", [5, 30])
def test_full_ten_node_execution(cleanup, tmp_path, batch_size, fixed_batch_size):
    fixed_batch_size.return_value = batch_size
    kube = cluster()
    cleanup.return_value = {"pvc_remaining": 0, "pv_remaining": 0,
                            "volume_attachments_remaining": 0}
    path = tmp_path / "report.json"
    report = disk.execute(kube, 10, "cas=dedicated", "managed-csi", 30, 30, 1, path)
    assert report["result"] == "success"
    assert report["disks_per_node"] == 8
    assert report["pod_count"] == 80
    assert report["pod_readiness_e2e_seconds"]["sample_count"] == 80
    assert report["pod_readiness_e2e_seconds"]["complete"]
    assert sum(
        stage["pod_readiness_e2e_seconds"]["sample_count"] for stage in report["stages"]
    ) == 80
    assert len(report["stages"]) == 1 + (79 + batch_size - 1) // batch_size
    assert report["stages"][0]["phase"] == "bootstrap"
    assert report["stages"][0]["replicas"] == 1
    assert report["stages"][0]["node_count"] == 1
    assert report["stages"][0]["evidence"]["triggered_scale_up"]
    assert all(stage["evidence"] for stage in report["stages"] if stage["phase"] == "overflow")
    assert all(stage["new_pod_count"] <= batch_size for stage in report["stages"])
    assert set(report["stages"][-1]["pods_per_node"].values()) == {8}
    assert json.loads(path.read_text()) == report
    assert [call.args[2]["spec"]["replicas"]
            for call in kube.app.patch_namespaced_stateful_set_scale.call_args_list] == [1] + [
        replicas for _, replicas, _ in disk.stage_targets(10, 8)
    ]
    manifest = kube.app.create_namespaced_stateful_set.call_args.args[1]
    assert manifest["spec"]["template"]["spec"]["nodeSelector"] == {"cas": "dedicated"}
    assert manifest["spec"]["replicas"] == 0
    assert manifest["spec"]["volumeClaimTemplates"][0]["spec"]["storageClassName"] == "managed-csi"
    cleanup.assert_called_once()


@patch.object(disk, "cleanup")
def test_failed_stage_is_reported_and_cleaned(cleanup, tmp_path):
    kube = cluster()
    cleanup.return_value = {}
    kube.app.patch_namespaced_stateful_set_scale.side_effect = RuntimeError("API failure")
    path = tmp_path / "report.json"
    with pytest.raises(RuntimeError, match="API failure"):
        disk.execute(kube, 10, "cas=dedicated", "managed-csi", 30, 30, 1, path)
    report = json.loads(path.read_text())
    assert report["result"] == "failure"
    assert report["error"] == "API failure"
    cleanup.assert_called_once()


@patch.object(disk, "cleanup")
def test_cleanup_failure_fails_successful_run(cleanup, tmp_path):
    cleanup.side_effect = TimeoutError("disk still attached")
    path = tmp_path / "report.json"
    with pytest.raises(TimeoutError, match="disk still attached"):
        disk.execute(cluster(), 2, "cas=dedicated", "managed-csi", 30, 30, 1, path)
    report = json.loads(path.read_text())
    assert report["result"] == "failure"
    assert report["cleanup_error"] == "disk still attached"


@pytest.mark.parametrize("invalid", ["existing_nodes", "storage", "target", "timeout"])
def test_preflight_does_not_mutate_cluster(invalid, tmp_path, fixed_batch_size):
    kube = cluster()
    target, timeout = 10, 30
    if invalid == "existing_nodes":
        kube.get_nodes.side_effect = None
        kube.get_nodes.return_value = [node()]
    elif invalid == "storage":
        kube.storage.read_storage_class.return_value.reclaim_policy = "Retain"
    elif invalid == "target":
        target = 5000
    else:
        timeout = 0
    path = tmp_path / "report.json"
    with pytest.raises(ValueError):
        disk.execute(kube, target, "cas=dedicated", "managed-csi", timeout, 30, 1, path)
    kube.api.create_namespace.assert_not_called()
    kube.app.patch_namespaced_stateful_set_scale.assert_not_called()
    fixed_batch_size.assert_not_called()
    assert json.loads(path.read_text())["result"] == "failure"


def test_missing_scale_up_evidence_times_out():
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(disk.WORKLOAD, "test", {"spec": {"replicas": 9}})
    kube.api.list_namespaced_event.side_effect = None
    kube.api.list_namespaced_event.return_value = Obj(items=[
        event("FailedScheduling", "Insufficient cpu"),
        event("TriggeredScaleUp", "scale"),
    ])
    with pytest.raises(TimeoutError, match="evidence=None"):
        disk.wait_for_stage(kube, "test", "cas=dedicated", 9, 2, 8,
                            {"node-0"}, True, timeout=0)


def test_rejects_extra_nodes():
    kube = cluster()
    kube.get_nodes.side_effect = None
    kube.get_nodes.return_value = [node(), node("node-1")]
    with pytest.raises(ValueError, match="found 2"):
        disk.wait_for_stage(kube, "test", "cas=dedicated", 8, 1, 8,
                            {"node-0"}, False, 0)


def test_running_without_storage_readiness_is_not_success():
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(disk.WORKLOAD, "test", {"spec": {"replicas": 8}})
    pods = [pod(index) for index in range(8)]
    pods[0].status.conditions[0].status = "False"
    kube.api.list_namespaced_pod.side_effect = None
    kube.api.list_namespaced_pod.return_value = Obj(items=pods)
    with pytest.raises(TimeoutError):
        disk.wait_for_stage(kube, "test", "cas=dedicated", 8, 1, 8,
                            {"node-0"}, False, 0)


def test_overflow_must_land_on_new_node():
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(disk.WORKLOAD, "test", {"spec": {"replicas": 9}})
    pods = [pod(index) for index in range(9)]
    pods[-1].spec.node_name = "node-0"
    kube.api.list_namespaced_pod.side_effect = None
    kube.api.list_namespaced_pod.return_value = Obj(items=pods)
    with pytest.raises(ValueError, match="newly added node"):
        disk.wait_for_stage(kube, "test", "cas=dedicated", 9, 2, 8,
                            {"node-0"}, True, 0)


def test_growth_accepts_evidence_from_any_new_pod_not_just_the_last():
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(
        disk.WORKLOAD, "test", {"spec": {"replicas": 11}}
    )
    pods = [pod(index) for index in range(11)]
    pods[7].spec.node_name, pods[10].spec.node_name = "node-1", "node-0"
    kube.api.list_namespaced_pod.side_effect = None
    kube.api.list_namespaced_pod.return_value = Obj(items=pods)
    kube.storage.list_volume_attachment.side_effect = None
    attachments = [attachment(index) for index in range(11)]
    attachments[7].spec.node_name, attachments[10].spec.node_name = "node-1", "node-0"
    kube.storage.list_volume_attachment.return_value = Obj(items=attachments)
    kube.api.list_namespaced_event.side_effect = lambda _, field_selector: Obj(items=[
        event("FailedScheduling", "1 node(s) exceed max volume count", "disk-workload-7"),
        event("TriggeredScaleUp", "scale", "disk-workload-7"),
    ] if field_selector == "involvedObject.name=disk-workload-7" else [])
    stage, _ = disk.wait_for_stage(
        kube, "test", "cas=dedicated", 11, 2, 8, {"node-0"}, True, 0,
        previous_replicas=6,
    )
    assert stage["evidence"]["pod_name"] == "disk-workload-7"
    assert stage["pods_per_node"] == {"node-0": 8, "node-1": 3}
    assert stage["pod_readiness_e2e_seconds"]["sample_count"] == 5


@pytest.mark.parametrize("new_pod_on_every_new_node", [True, False])
def test_one_batch_can_add_multiple_nodes(new_pod_on_every_new_node):
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(
        disk.WORKLOAD, "test", {"spec": {"replicas": 25}}
    )
    if not new_pod_on_every_new_node:
        pods = [pod(index) for index in range(25)]
        pods[0].spec.node_name, pods[24].spec.node_name = "node-3", "node-0"
        kube.api.list_namespaced_pod.side_effect = None
        kube.api.list_namespaced_pod.return_value = Obj(items=pods)
        with pytest.raises(ValueError, match="every newly added node"):
            disk.wait_for_stage(
                kube, "test", "cas=dedicated", 25, 4, 8, {"node-0"}, True, 0,
                previous_replicas=6,
            )
    else:
        stage, nodes = disk.wait_for_stage(
            kube, "test", "cas=dedicated", 25, 4, 8, {"node-0"}, True, 0,
            previous_replicas=6,
        )
        assert nodes == {"node-0", "node-1", "node-2", "node-3"}
        assert set(stage["timings"]["nodes"]) == {"node-1", "node-2", "node-3"}
        assert stage["pods_per_node"] == {
            "node-0": 8, "node-1": 8, "node-2": 8, "node-3": 1,
        }


def test_new_nodes_must_advertise_same_disk_limit():
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(disk.WORKLOAD, "test", {"spec": {"replicas": 9}})
    kube.storage.read_csi_node.side_effect = lambda name: Obj(spec=Obj(drivers=[
        Obj(name=disk.DRIVER, allocatable=Obj(count=8 if name == "node-0" else 4))
    ]))
    with pytest.raises(ValueError, match="different disk limits"):
        disk.wait_for_stage(kube, "test", "cas=dedicated", 9, 2, 8,
                            {"node-0"}, True, 0)


@pytest.mark.parametrize("invalid", ["shared", "unattached", "wrong_driver", "density"])
def test_disk_verification_rejects_false_success(invalid):
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(disk.WORKLOAD, "test", {"spec": {"replicas": 8}})
    pods = [pod(index) for index in range(8)]
    if invalid == "shared":
        kube.api.read_persistent_volume.side_effect = lambda _: volume(0)
    elif invalid == "unattached":
        kube.storage.list_volume_attachment.side_effect = None
        kube.storage.list_volume_attachment.return_value = Obj(items=[])
    elif invalid == "wrong_driver":
        wrong = volume(0)
        wrong.spec.csi.driver = "other"
        kube.api.read_persistent_volume.side_effect = lambda _: wrong
    else:
        pods.pop()
    with pytest.raises(ValueError):
        disk.verify_disks(kube, "test", pods, {"node-0"}, 8, full=True)


@patch.object(disk.time, "sleep")
def test_cleanup_tracks_attachment_after_pv_disappears(sleep, tmp_path):
    kube = cluster()
    kube.api.list_persistent_volume.side_effect = [
        Obj(items=[volume(0)]), Obj(items=[]), Obj(items=[]),
    ]
    kube.api.list_persistent_volume_claim_for_all_namespaces.return_value = Obj(items=[])
    kube.storage.list_volume_attachment.side_effect = [
        Obj(items=[attachment(0)]), Obj(items=[]),
    ]
    result = disk.cleanup(kube, "test", "cas=dedicated", 30, 1, tmp_path / "cleanup.json")
    assert result["volume_attachments_remaining"] == 0
    kube.api.delete_namespace.assert_called_once_with("test")
    sleep.assert_called_once_with(10)


def test_cleanup_node_timeout(tmp_path):
    kube = cluster()
    kube.api.list_persistent_volume.return_value = Obj(items=[])
    kube.api.list_persistent_volume_claim_for_all_namespaces.return_value = Obj(items=[])
    kube.get_nodes.side_effect = None
    kube.get_nodes.return_value = [node()]
    with pytest.raises(TimeoutError, match="did not return to zero"):
        disk.cleanup(kube, "test", "cas=dedicated", 0, 1, tmp_path / "cleanup.json")


def test_cleanup_storage_timeout_preserves_attachment_check(tmp_path):
    kube = cluster()
    kube.api.list_persistent_volume.return_value = Obj(items=[volume(0)])
    kube.api.list_persistent_volume_claim_for_all_namespaces.return_value = Obj(items=[])
    kube.storage.list_volume_attachment.side_effect = None
    kube.storage.list_volume_attachment.return_value = Obj(items=[attachment(0)])
    with pytest.raises(TimeoutError, match="Storage cleanup timed out"):
        disk.cleanup(kube, "test", "cas=dedicated", 30, 0, tmp_path / "cleanup.json")


def test_collect_preserves_structured_report(tmp_path, monkeypatch):
    for key, value in {"CLOUD_INFO": '{"cloud":"azure"}', "RUN_ID": "run",
                       "RUN_URL": "https://example.test/run"}.items():
        monkeypatch.setenv(key, value)
    metrics = {"sample_count": 80, "expected_pod_count": 80, "complete": True,
               "p50": 10.0, "p90": 20.0, "p99": 30.0}
    report = {"node_count": 10, "pod_count": 80, "result": "success", "stages": [],
              "pod_readiness_e2e_seconds": metrics}
    report_file, result_file = tmp_path / "report.json", tmp_path / "results.json"
    report_file.write_text(json.dumps(report))
    disk.collect(report_file, result_file)
    result = json.loads(result_file.read_text())
    assert result["data"] == report
    assert result["autoscale_type"] == "disk_boundary"
    assert result["node_count"] == 10
    assert result["pod_count"] == 80
    assert result["data"]["pod_readiness_e2e_seconds"] == metrics


def test_readiness_percentiles_use_individual_samples_and_linear_interpolation():
    samples = {
        f"pod-{index}": {"pod_uid": str(index), "e2e_ready_seconds": seconds}
        for index, seconds in enumerate(range(10, 101, 10))
    }
    metrics = disk.summarize_pod_readiness(samples, 10)
    assert metrics["sample_count"] == 10
    assert metrics["complete"]
    assert metrics["p50"] == pytest.approx(55)
    assert metrics["p90"] == pytest.approx(91)
    assert metrics["p99"] == pytest.approx(99.1)


@pytest.mark.parametrize("samples,expected", [
    ({}, 3),
    ({"pod": {"pod_uid": "uid", "e2e_ready_seconds": 10}}, 3),
    ({"pod": {"pod_uid": "uid", "e2e_ready_seconds": 10}}, None),
])
def test_incomplete_readiness_does_not_publish_success_biased_percentiles(samples, expected):
    metrics = disk.summarize_pod_readiness(samples, expected)
    assert not metrics["complete"]
    assert metrics["sample_count"] == len(samples)
    assert metrics["expected_pod_count"] == expected
    assert metrics["p50"] is metrics["p90"] is metrics["p99"] is None


def test_single_pod_percentiles_all_equal_its_latency():
    metrics = disk.summarize_pod_readiness(
        {"pod": {"pod_uid": "uid", "e2e_ready_seconds": 137.2}}, 1
    )
    assert metrics["p50"] == metrics["p90"] == metrics["p99"] == 137.2


@patch.object(disk.time, "sleep")
@patch.object(disk.time, "monotonic", side_effect=[0, 10, 11, 20, 21, 30])
def test_readiness_tracks_new_pods_once_at_their_first_observed_ready_time(_clock, _sleep):
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(
        disk.WORKLOAD, "test", {"spec": {"replicas": 8}}
    )

    def snapshot(ready_through):
        pods = [pod(index) for index in range(8)]
        for index in range(ready_through + 1, 8):
            pods[index].status.conditions[0].status = "False"
        return Obj(items=pods)

    kube.api.list_namespaced_pod.side_effect = [snapshot(5), snapshot(6), snapshot(7)]
    stage, _ = disk.wait_for_stage(
        kube, "test", "cas=dedicated", 8, 1, 8, {"node-0"}, False, 100,
        previous_replicas=5,
    )
    assert stage["pod_readiness_samples"] == {
        "disk-workload-5": {"pod_uid": "disk-workload-5", "e2e_ready_seconds": 10},
        "disk-workload-6": {"pod_uid": "disk-workload-6", "e2e_ready_seconds": 20},
        "disk-workload-7": {"pod_uid": "disk-workload-7", "e2e_ready_seconds": 30},
    }
    metrics = stage["pod_readiness_e2e_seconds"]
    assert metrics["sample_count"] == 3
    assert metrics["p50"] == 20
    assert metrics["p90"] == pytest.approx(28)
    assert metrics["p99"] == pytest.approx(29.8)


@patch.object(disk.time, "sleep")
@patch.object(disk.time, "monotonic", side_effect=[0, 10, 11, 20])
def test_readiness_replaces_sample_when_pod_uid_changes(_clock, _sleep):
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(
        disk.WORKLOAD, "test", {"spec": {"replicas": 8}}
    )
    first = [pod(index) for index in range(8)]
    first[7].status.conditions[0].status = "False"
    second = [pod(index) for index in range(8)]
    second[6].metadata.uid = "replacement-uid"
    kube.api.list_namespaced_pod.side_effect = [Obj(items=first), Obj(items=second)]
    stage, _ = disk.wait_for_stage(
        kube, "test", "cas=dedicated", 8, 1, 8, {"node-0"}, False, 100,
        previous_replicas=5,
    )
    assert stage["pod_readiness_samples"]["disk-workload-5"]["e2e_ready_seconds"] == 10
    assert stage["pod_readiness_samples"]["disk-workload-6"] == {
        "pod_uid": "replacement-uid", "e2e_ready_seconds": 20,
    }
    assert stage["timings"]["pods"]["disk-workload-6"]["pod_uid"] == "replacement-uid"
    assert stage["timings"]["pods"]["disk-workload-6"]["e2e_ready_seconds"] == 20


@patch.object(disk, "cleanup", return_value={})
def test_timeout_preserves_partial_samples_and_incomplete_run_summary(_cleanup, tmp_path):
    original_wait = disk.wait_for_stage

    def wait(*args, **kwargs):
        if args[3] == 1:
            return original_wait(*args, **kwargs)
        kwargs["readiness_samples"]["disk-workload-1"] = {
            "pod_uid": "uid-1", "e2e_ready_seconds": 15,
        }
        raise TimeoutError("Pods did not become Ready")

    path = tmp_path / "report.json"
    with patch.object(disk, "wait_for_stage", side_effect=wait):
        with pytest.raises(TimeoutError, match="did not become Ready"):
            disk.execute(cluster(), 10, "cas=dedicated", "managed-csi", 30, 30, 1, path)
    report = json.loads(path.read_text())
    assert report["result"] == "failure"
    assert report["pod_readiness_e2e_seconds"]["sample_count"] == 2
    assert report["pod_readiness_e2e_seconds"]["expected_pod_count"] == 80
    assert not report["pod_readiness_e2e_seconds"]["complete"]
    assert report["pod_readiness_e2e_seconds"]["p99"] is None
    failed_stage = report["stages"][-1]
    assert failed_stage["result"] == "failure"
    assert failed_stage["pod_readiness_e2e_seconds"]["sample_count"] == 1
    assert failed_stage["pod_readiness_e2e_seconds"]["expected_pod_count"] == 5
    assert failed_stage["pod_readiness_e2e_seconds"]["p50"] is None


@patch.object(disk, "cleanup", return_value={})
def test_run_percentiles_combine_pods_instead_of_averaging_batch_percentiles(_cleanup, tmp_path):
    latencies = {1: [100], 6: [10, 10, 10, 10, 10], 8: [200, 200]}

    def wait(*args, **kwargs):
        replicas, expected_nodes = args[3:5]
        previous_replicas = kwargs["previous_replicas"]
        for index, seconds in enumerate(latencies[replicas], previous_replicas):
            kwargs["readiness_samples"][f"disk-workload-{index}"] = {
                "pod_uid": f"uid-{index}", "e2e_ready_seconds": seconds,
            }
        return {"disks_per_node": 4}, {
            f"node-{index}" for index in range(expected_nodes)
        }

    with patch.object(disk, "wait_for_stage", side_effect=wait):
        report = disk.execute(
            cluster(4), 2, "cas=dedicated", "managed-csi", 30, 30, 1, tmp_path / "report.json"
        )
    metrics = report["pod_readiness_e2e_seconds"]
    assert metrics["sample_count"] == 8
    assert metrics["complete"]
    assert metrics["p50"] == 10
    assert metrics["p90"] == 200
    assert metrics["p99"] == 200


@patch.object(disk, "cleanup", return_value={})
def test_readiness_latency_includes_replica_change_api_time(_cleanup, tmp_path):
    kube = cluster(4)
    clock = [0]
    original_scale = kube.app.patch_namespaced_stateful_set_scale.side_effect

    def scale(*args):
        clock[0] += 10
        original_scale(*args)

    kube.app.patch_namespaced_stateful_set_scale.side_effect = scale
    with patch.object(disk.time, "monotonic", side_effect=lambda: clock[0]):
        report = disk.execute(
            kube, 2, "cas=dedicated", "managed-csi", 30, 30, 1, tmp_path / "report.json"
        )
    assert report["pod_readiness_e2e_seconds"]["p50"] == 10
    assert report["pod_readiness_e2e_seconds"]["p90"] == 10
    assert report["pod_readiness_e2e_seconds"]["p99"] == 10


def test_wait_timeout_retains_observed_samples_for_caller():
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(
        disk.WORKLOAD, "test", {"spec": {"replicas": 8}}
    )
    pods = [pod(index) for index in range(8)]
    pods[-1].status.conditions[0].status = "False"
    kube.api.list_namespaced_pod.side_effect = None
    kube.api.list_namespaced_pod.return_value = Obj(items=pods)
    samples = {}
    with pytest.raises(TimeoutError):
        disk.wait_for_stage(
            kube, "test", "cas=dedicated", 8, 1, 8, {"node-0"}, False, 0,
            previous_replicas=5, readiness_samples=samples,
        )
    assert set(samples) == {"disk-workload-5", "disk-workload-6"}


@patch.object(disk.time, "sleep")
@patch.object(disk.time, "monotonic", side_effect=[5, 6, 15, 16, 30])
def test_pod_e2e_includes_waiting_for_new_node_and_records_timestamps(_clock, _sleep):
    requested_at = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(
        disk.WORKLOAD, "test", {"spec": {"replicas": 1}}
    )
    new_node = node()
    new_node.metadata.uid = "node-uid"
    new_node.metadata.creation_timestamp = requested_at + timedelta(seconds=12)
    new_node.status.conditions[0].last_transition_time = requested_at + timedelta(seconds=14)
    kube.get_nodes.side_effect = [[], [new_node], [new_node]]

    def snapshot(phase, ready):
        resource = pod(0)
        resource.metadata.creation_timestamp = requested_at + timedelta(seconds=1)
        resource.status.start_time = (
            requested_at + timedelta(seconds=13) if phase == "Running" else None
        )
        resource.status.phase = phase
        resource.status.conditions[0].status = "True" if ready else "False"
        resource.status.conditions[0].last_transition_time = (
            requested_at + timedelta(seconds=28) if ready else None
        )
        return Obj(items=[resource])

    kube.api.list_namespaced_pod.side_effect = [
        snapshot("Pending", False), snapshot("Running", False), snapshot("Running", True),
    ]
    timings = disk.create_stage_timings(requested_at.isoformat(), 0, 1)
    with patch.object(disk, "datetime") as clock:
        clock.now.side_effect = [
            requested_at + timedelta(seconds=value) for value in (5, 15, 30)
        ]
        stage, _ = disk.wait_for_stage(
            kube, "test", "cas=dedicated", 1, 1, None, set(), True, 100,
            started=0, timings=timings,
        )
    pod_row = stage["timings"]["pods"]["disk-workload-0"]
    node_row = stage["timings"]["nodes"]["node-0"]
    assert pod_row["requested_at"] == node_row["requested_at"] == requested_at.isoformat()
    assert pod_row["pod_created_at"] == (requested_at + timedelta(seconds=1)).isoformat()
    assert pod_row["pod_started_at"] == (requested_at + timedelta(seconds=13)).isoformat()
    assert pod_row["ready_transition_at"] == (requested_at + timedelta(seconds=28)).isoformat()
    assert pod_row["ready_observed_at"] == (requested_at + timedelta(seconds=30)).isoformat()
    assert node_row["node_registered_at"] == (requested_at + timedelta(seconds=12)).isoformat()
    assert node_row["ready_observed_at"] == (requested_at + timedelta(seconds=15)).isoformat()
    assert node_row["ready_transition_at"] == (requested_at + timedelta(seconds=14)).isoformat()
    assert node_row["node_uid"] == "node-uid"
    assert node_row["e2e_ready_seconds"] == 15
    assert pod_row["e2e_ready_seconds"] == 30
    assert stage["pod_readiness_e2e_seconds"]["p50"] == 30
    assert pod_row["node_name"] == node_row["node_name"]


@patch.object(disk, "cleanup", return_value={})
def test_exports_one_timing_row_per_pod_and_new_workload_node(_cleanup, tmp_path):
    report = disk.execute(
        cluster(4), 2, "cas=dedicated", "managed-csi", 30, 30, 1, tmp_path / "report.json"
    )
    assert len(report["pod_timings"]) == 8
    assert len(report["node_timings"]) == 2
    assert len({row["pod_name"] for row in report["pod_timings"]}) == 8
    assert {row["node_name"] for row in report["node_timings"]} == {"node-0", "node-1"}
    assert all(row["ready_observed_at"] for row in report["pod_timings"])
    assert all(row["ready_observed_at"] for row in report["node_timings"])
    for kind, expected_count, columns in [
        ("pod", 8, disk.POD_TIMING_COLUMNS), ("node", 2, disk.NODE_TIMING_COLUMNS),
    ]:
        with (tmp_path / f"{kind}-readiness.csv").open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            assert reader.fieldnames == list(columns)
            rows = list(reader)
        assert len(rows) == expected_count
        assert all(float(row["e2e_ready_seconds"]) >= 0 for row in rows)
    assert json.loads((tmp_path / "report.json").read_text()) == report


def test_timing_export_retains_requested_pods_that_never_appeared(tmp_path):
    timings = disk.create_stage_timings("2026-10-20T12:00:00+00:00", 1, 4)
    report = {"stages": [{"timings": timings}]}
    disk.write_timing_tables(report, tmp_path / "report.json")
    assert len(report["pod_timings"]) == 3
    assert report["node_timings"] == []
    assert all(row["phase"] == "NotObserved" for row in report["pod_timings"])
    assert all(row["ready_observed_at"] is None for row in report["pod_timings"])
    assert all(row["e2e_ready_seconds"] is None for row in report["pod_timings"])
    with (tmp_path / "pod-readiness.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 3
    assert all(row["e2e_ready_seconds"] == "" for row in rows)


def test_pending_pod_and_unready_node_keep_null_completion_times():
    kube = cluster()
    kube.app.patch_namespaced_stateful_set_scale(
        disk.WORKLOAD, "test", {"spec": {"replicas": 1}}
    )
    unready_node = node()
    unready_node.status.conditions[0].status = "False"
    kube.get_nodes.side_effect = None
    kube.get_nodes.return_value = [unready_node]
    pending = pod(0)
    pending.status.phase = "Pending"
    pending.status.conditions[0].status = "False"
    kube.api.list_namespaced_pod.side_effect = None
    kube.api.list_namespaced_pod.return_value = Obj(items=[pending])
    timings = disk.create_stage_timings("2026-10-20T12:00:00+00:00", 0, 1)
    with pytest.raises(TimeoutError):
        disk.wait_for_stage(
            kube, "test", "cas=dedicated", 1, 1, None, set(), True, 0, timings=timings,
        )
    assert timings["pods"]["disk-workload-0"]["phase"] == "Pending"
    for row in [timings["pods"]["disk-workload-0"], timings["nodes"]["node-0"]]:
        assert row["ready_observed_at"] is None
        assert row["e2e_ready_seconds"] is None


@patch.object(disk, "cleanup", return_value={})
@patch.object(disk.csv, "DictWriter", side_effect=OSError("CSV write failed"))
def test_csv_failure_still_saves_json_and_fails_the_run(_writer, _cleanup, tmp_path):
    path = tmp_path / "report.json"
    with pytest.raises(OSError, match="CSV write failed"):
        disk.execute(cluster(4), 2, "cas=dedicated", "managed-csi", 30, 30, 1, path)
    report = json.loads(path.read_text())
    assert report["result"] == "failure"
    assert report["timing_export_error"] == "CSV write failed"
    assert len(report["pod_timings"]) == 8
    assert len(report["node_timings"]) == 2
