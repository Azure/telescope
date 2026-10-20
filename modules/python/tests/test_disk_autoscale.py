import json
from types import SimpleNamespace as Obj
from unittest.mock import MagicMock, patch

import pytest

from clusterloader2.autoscale import disk_autoscale as disk


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


def test_ten_node_stage_targets():
    targets = list(disk.stage_targets(10, 8))
    assert len(targets) == 19
    assert targets[:4] == [(1, 8, False), (2, 9, True), (2, 16, False), (3, 17, True)]
    assert targets[-2:] == [(10, 73, True), (10, 80, False)]


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
    assert disk.scale_up_evidence(events, "disk-workload-8", 2) is None
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
    assert [stage["replicas"] for stage in report["stages"][:5]] == [1, 4, 5, 8, 9]
    assert set(report["stages"][-1]["pods_per_node"].values()) == {4}


@patch.object(disk, "cleanup")
def test_full_ten_node_execution(cleanup, tmp_path):
    kube = cluster()
    cleanup.return_value = {"pvc_remaining": 0, "pv_remaining": 0,
                            "volume_attachments_remaining": 0}
    path = tmp_path / "report.json"
    report = disk.execute(kube, 10, "cas=dedicated", "managed-csi", 30, 30, 1, path)
    assert report["result"] == "success"
    assert report["disks_per_node"] == 8
    assert report["pod_count"] == 80
    assert len(report["stages"]) == 20
    assert report["stages"][0]["phase"] == "bootstrap"
    assert report["stages"][0]["replicas"] == 1
    assert report["stages"][0]["node_count"] == 1
    assert report["stages"][0]["evidence"]["triggered_scale_up"]
    assert sum(stage["phase"] == "overflow" for stage in report["stages"]) == 9
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
def test_preflight_does_not_mutate_cluster(invalid, tmp_path):
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
    report = {"node_count": 10, "pod_count": 80, "result": "success", "stages": []}
    report_file, result_file = tmp_path / "report.json", tmp_path / "results.json"
    report_file.write_text(json.dumps(report))
    disk.collect(report_file, result_file)
    result = json.loads(result_file.read_text())
    assert result["data"] == report
    assert result["autoscale_type"] == "disk_boundary"
    assert result["node_count"] == 10
    assert result["pod_count"] == 80
