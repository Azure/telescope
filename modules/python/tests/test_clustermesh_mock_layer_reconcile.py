"""Tests for the mock-layer reconciler (mock_layer_reconcile.py).

Uses a small in-memory fake `kubectl` (monkeypatching `subprocess.run` inside the
reconciler module) instead of a real cluster, consistent with how the existing
telemetry-audit tests fake their HTTP layer (see test_clustermesh_telemetry_audit.py).
"""
# pylint: disable=too-many-lines

import importlib.util
import json
import types
from pathlib import Path

import yaml


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "clusterloader2"
    / "clustermesh-scale"
    / "mock_layer_reconcile.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "mock_layer_reconcile",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise ImportError(f"Unable to load module from {MODULE_PATH}")
reconciler = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(reconciler)


NAMESPACE = "mock-clustermesh"
IMAGE = "example.azurecr.io/mock-cilium-agent:v26"
SERVICE_ACCOUNT = "mock-cilium-agent"
HEALTHY_REAL_NODE = "aks-real-0"


# ---------------------------------------------------------------------------
# Desired-state fixtures (mirrors what provision-kwok-layer.sh persists).
# ---------------------------------------------------------------------------

def _node_doc(index):
    name = f"kwok-node-{index}"
    return {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {
            "name": name,
            "annotations": {
                "node.alpha.kubernetes.io/ttl": "0",
                "kwok.x-k8s.io/node": "fake",
            },
            "labels": {"type": "kwok", "kubernetes.io/hostname": name},
        },
        "spec": {
            "providerID": f"kwok://{name}",
            "podCIDR": f"100.1.{index}.0/24",
            "podCIDRs": [f"100.1.{index}.0/24"],
        },
    }


def _agent_doc(index):
    node_name = f"kwok-node-{index}"
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": f"mock-cilium-agent-{index}",
            "namespace": NAMESPACE,
            "labels": {
                "app": "mock-cilium-agent",
                "mock-clustermesh/serves-node": node_name,
            },
        },
        "spec": {
            "serviceAccountName": SERVICE_ACCOUNT,
            "restartPolicy": "OnFailure",
            "containers": [
                {
                    "name": "mock-cilium-agent",
                    "image": IMAGE,
                    "env": [{"name": "K8S_NODE_NAME", "value": node_name}],
                }
            ],
        },
    }


def _node_doc_with_taint(index):
    doc = _node_doc(index)
    doc["spec"]["taints"] = [
        {"key": "mock-clustermesh/kwok", "value": "true", "effect": "NoSchedule"},
    ]
    return doc


def _agent_doc_with_clustermesh(index, cluster_id="1"):
    """An agent doc that also wires the clustermesh consume path (the
    --cluster-id/--clustermesh-config args + matching volume/volumeMount)."""
    doc = _agent_doc(index)
    container = doc["spec"]["containers"][0]
    container["args"] = [
        f"--cluster-id={cluster_id}",
        "--clustermesh-config=/var/lib/cilium/clustermesh/",
    ]
    container["volumeMounts"] = [
        {
            "name": "clustermesh-secrets",
            "mountPath": "/var/lib/cilium/clustermesh",
            "readOnly": True,
        },
    ]
    doc["spec"]["volumes"] = [
        {"name": "clustermesh-secrets", "secret": {"secretName": "cilium-clustermesh"}},
    ]
    return doc


def write_state_dir(
    state_root, role, node_count, metadata_overrides=None,
    node_doc_fn=_node_doc, agent_doc_fn=_agent_doc,
):
    """Write nodes.yaml / agents.yaml / metadata.json for `role` under state_root.

    `metadata_overrides` merges into (overwrites) the default metadata dict --
    used by tests that need run_id / consume_clustermesh set. `node_doc_fn` /
    `agent_doc_fn` are index -> doc factories, overridable per test to exercise
    drift in fields the default fixtures don't set (taints, clustermesh-config
    args/mounts/volumes, ...).
    """
    state_dir = state_root / role
    state_dir.mkdir(parents=True, exist_ok=True)
    node_docs = [node_doc_fn(i) for i in range(node_count)]
    agent_docs = [agent_doc_fn(i) for i in range(node_count)]
    (state_dir / "nodes.yaml").write_text(
        "".join(f"---\n{yaml.safe_dump(doc)}" for doc in node_docs), encoding="utf-8",
    )
    (state_dir / "agents.yaml").write_text(
        "".join(f"---\n{yaml.safe_dump(doc)}" for doc in agent_docs), encoding="utf-8",
    )
    metadata = {
        "schema_version": 1,
        "agent_namespace": NAMESPACE,
        "node_count": node_count,
        "cluster_name": role,
    }
    if metadata_overrides:
        metadata.update(metadata_overrides)
    (state_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return node_docs, agent_docs


# ---------------------------------------------------------------------------
# KWOK support-manifest fixtures (kwok-controller / stage-fast / kwok-apf / rbac).
# ---------------------------------------------------------------------------

def _support_kwok_controller_docs(available_replicas=1, desired_replicas=1):
    return [{
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "kwok-controller", "namespace": "kube-system"},
        "spec": {"replicas": desired_replicas},
        "status": {"availableReplicas": available_replicas},
    }]


def _support_stage_docs(names=("node-fast-ready", "pod-fast-ready")):
    return [
        {"apiVersion": "kwok.x-k8s.io/v1alpha1", "kind": "Stage", "metadata": {"name": name}}
        for name in names
    ]


def _support_apf_docs():
    return [
        {
            "apiVersion": "flowcontrol.apiserver.k8s.io/v1",
            "kind": "PriorityLevelConfiguration",
            "metadata": {"name": "kwok-controller"},
        },
        {
            "apiVersion": "flowcontrol.apiserver.k8s.io/v1",
            "kind": "FlowSchema",
            "metadata": {"name": "kwok-controller"},
        },
    ]


def _support_rbac_docs():
    return [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE}},
        {
            "apiVersion": "v1", "kind": "ServiceAccount",
            "metadata": {"name": SERVICE_ACCOUNT, "namespace": NAMESPACE},
        },
        {
            "apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
            "metadata": {"name": f"{SERVICE_ACCOUNT}-cluster-admin"},
        },
    ]


def write_support_manifests(state_root, role, **overrides):
    """Write support/{kwok-controller,stage-fast,kwok-apf,rbac}.yaml under a
    previously-written state dir, mirroring provision-kwok-layer.sh Step 3.5.
    """
    support_dir = state_root / role / "support"
    support_dir.mkdir(parents=True, exist_ok=True)
    docs_by_file = {
        "kwok-controller.yaml": overrides.get("kwok_controller", _support_kwok_controller_docs()),
        "stage-fast.yaml": overrides.get("stage", _support_stage_docs()),
        "kwok-apf.yaml": overrides.get("apf", _support_apf_docs()),
        "rbac.yaml": overrides.get("rbac", _support_rbac_docs()),
    }
    for filename, docs in docs_by_file.items():
        (support_dir / filename).write_text(
            "".join(f"---\n{yaml.safe_dump(doc)}" for doc in docs), encoding="utf-8",
        )
    return docs_by_file


def _clustermesh_secret_docs(data=None):
    """The four kube-system source secrets the consume path copies."""
    data = data if data is not None else {"placeholder": "c291cmNl"}  # "source" base64
    return {
        name: {
            "apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": name, "namespace": reconciler.CLUSTERMESH_SOURCE_NAMESPACE},
            "type": "Opaque",
            "data": dict(data),
        }
        for name in reconciler.CLUSTERMESH_SECRET_NAMES
    }


# ---------------------------------------------------------------------------
# Fake kubectl: a tiny in-memory cluster driven purely by the `subprocess.run`
# calls the reconciler issues (get -o json / apply -f - / delete --wait=false).
# ---------------------------------------------------------------------------

def _completed(stdout):
    return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _failed(stderr):
    return types.SimpleNamespace(returncode=1, stdout="", stderr=stderr)


def _namespace_of(cmd):
    if "-n" in cmd:
        return cmd[cmd.index("-n") + 1]
    return None


class FakeKubeCluster:
    """Minimal fake standing in for a real apiserver across repair attempts."""

    # Kinds handled generically by name-only existence (support-infra objects
    # verified via kubectl_object_exists: a plain `get <kind> <name>`, no -o json).
    _EXISTENCE_ONLY_KINDS = {
        "stage", "prioritylevelconfiguration", "flowschema",
        "serviceaccount", "clusterrolebinding",
    }

    def __init__(
        self,
        healthy_real_node=HEALTHY_REAL_NODE,
        permanently_broken_pods=(),
        transient_get_failures=0,
    ):
        self.nodes = {}
        self.pods = {}  # (namespace, name) -> pod dict
        self.secrets = {}  # (namespace, name) -> secret dict
        self.deployments = {}  # (namespace, name) -> deployment dict
        self.existence_objects = set()  # (kind_lower, namespace_or_None, name)
        self.apply_calls = []
        self.delete_calls = []
        self.healthy_real_node = healthy_real_node
        self.permanently_broken_pods = set(permanently_broken_pods)
        self.transient_get_failures = transient_get_failures
        self.nodes[healthy_real_node] = {
            "metadata": {"name": healthy_real_node, "labels": {}},
            "spec": {},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }

    def add_real_node(self, name, ready=True):
        self.nodes[name] = {
            "metadata": {"name": name, "labels": {}},
            "spec": {},
            "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}]},
        }

    def add_secret(self, name, namespace, secret):
        self.secrets[(namespace, name)] = json.loads(json.dumps(secret))

    def add_support_infra(self, deployment_available_replicas=1, deployment_desired_replicas=1,
                           stage_names=("node-fast-ready", "pod-fast-ready"),
                           apf=True, service_account=True, cluster_role_binding=True):
        """Seed a fully-healthy KWOK support infra (all objects present)."""
        self.deployments[("kube-system", "kwok-controller")] = {
            "metadata": {"name": "kwok-controller", "namespace": "kube-system"},
            "spec": {"replicas": deployment_desired_replicas},
            "status": {"availableReplicas": deployment_available_replicas},
        }
        for stage_name in stage_names:
            self.existence_objects.add(("stage", None, stage_name))
        if apf:
            self.existence_objects.add(("prioritylevelconfiguration", None, "kwok-controller"))
            self.existence_objects.add(("flowschema", None, "kwok-controller"))
        if service_account:
            self.existence_objects.add(("serviceaccount", NAMESPACE, SERVICE_ACCOUNT))
        if cluster_role_binding:
            self.existence_objects.add(("clusterrolebinding", None, f"{SERVICE_ACCOUNT}-cluster-admin"))

    def seed(self, node_docs, agent_docs):
        for doc in node_docs:
            self._apply(dict(doc))
        for doc in agent_docs:
            self._apply(dict(doc))

    def run(self, cmd, input=None, capture_output=True, text=True,  # pylint: disable=redefined-builtin
             timeout=None, check=False):
        del capture_output, text, timeout, check  # unused; fake honors them implicitly
        if "get" in cmd and self.transient_get_failures > 0:
            self.transient_get_failures -= 1
            return _failed("transient apiserver error")
        if "get" in cmd and "nodes" in cmd:
            return _completed(json.dumps({"items": list(self.nodes.values())}))
        if "get" in cmd and "pods" in cmd:
            namespace = _namespace_of(cmd)
            items = [pod for (ns, _name), pod in self.pods.items() if ns == namespace]
            return _completed(json.dumps({"items": items}))
        if "get" in cmd and "secret" in cmd:
            idx = cmd.index("secret")
            name = cmd[idx + 1]
            namespace = _namespace_of(cmd)
            secret = self.secrets.get((namespace, name))
            if secret is None:
                return _failed(f'Error from server (NotFound): secrets "{name}" not found')
            return _completed(json.dumps(secret))
        if "get" in cmd and "deployment" in cmd:
            idx = cmd.index("deployment")
            name = cmd[idx + 1]
            namespace = _namespace_of(cmd)
            deployment = self.deployments.get((namespace, name))
            if deployment is None:
                return _failed(f'Error from server (NotFound): deployments.apps "{name}" not found')
            return _completed(json.dumps(deployment))
        if "get" in cmd and any(kind in cmd for kind in self._EXISTENCE_ONLY_KINDS):
            idx = cmd.index("get")
            kind = cmd[idx + 1]
            name = cmd[idx + 2]
            namespace = _namespace_of(cmd)
            if (kind, namespace, name) not in self.existence_objects:
                return _failed(f'Error from server (NotFound): {kind}s "{name}" not found')
            return _completed("")
        if "apply" in cmd:
            doc = yaml.safe_load(input)
            self.apply_calls.append(doc)
            self._apply(doc)
            return _completed("")
        if "delete" in cmd:
            idx = cmd.index("delete")
            kind, name = cmd[idx + 1], cmd[idx + 2]
            namespace = _namespace_of(cmd)
            self.delete_calls.append((kind, name))
            if kind == "node":
                self.nodes.pop(name, None)
            elif kind == "pod":
                self.pods.pop((namespace, name), None)
            return _completed("")
        raise AssertionError(f"unexpected fake kubectl invocation: {cmd}")

    def _apply(self, doc):
        kind = doc.get("kind")
        name = doc["metadata"]["name"]
        if kind == "Node":
            node = json.loads(json.dumps(doc))
            node.setdefault("status", {})["conditions"] = [{"type": "Ready", "status": "True"}]
            self.nodes[name] = node
        elif kind == "Pod":
            namespace = doc["metadata"].get("namespace", NAMESPACE)
            pod = json.loads(json.dumps(doc))
            pod.setdefault("spec", {})["nodeName"] = self.healthy_real_node
            if name in self.permanently_broken_pods:
                pod["status"] = {"phase": "CrashLoopBackOff", "containerStatuses": [{"ready": False}]}
            else:
                pod["status"] = {
                    "phase": "Running",
                    "containerStatuses": [{"ready": True}] * max(len(pod["spec"].get("containers", [])), 1),
                }
            self.pods[(namespace, name)] = pod
        elif kind == "Secret":
            namespace = doc["metadata"].get("namespace", NAMESPACE)
            self.secrets[(namespace, name)] = json.loads(json.dumps(doc))
        elif kind == "Deployment":
            namespace = doc["metadata"].get("namespace", "kube-system")
            deployment = json.loads(json.dumps(doc))
            # Re-applying (a repair) always brings the controller back healthy.
            deployment.setdefault("status", {})["availableReplicas"] = (
                deployment.get("spec") or {}
            ).get("replicas", 1)
            self.deployments[(namespace, name)] = deployment
        elif kind in ("Stage", "PriorityLevelConfiguration", "FlowSchema", "ClusterRoleBinding"):
            self.existence_objects.add((kind.lower(), None, name))
        elif kind == "ServiceAccount":
            namespace = doc["metadata"].get("namespace", NAMESPACE)
            self.existence_objects.add(("serviceaccount", namespace, name))
        elif kind == "Namespace":
            pass  # not independently tracked; existence isn't checked by the reconciler
        else:
            raise AssertionError(f"unexpected apply kind: {kind}")


def _reconcile(monkeypatch, cluster, role, state_root, **kwargs):
    monkeypatch.setattr(reconciler.subprocess, "run", cluster.run)
    defaults = {
        "kubeconfig": f"/kube/{role}.config",
        "state_root": str(state_root),
        "expected_count": None,
        "attempts": 3,
        "settle_seconds": 0,
        "request_timeout_seconds": 5,
    }
    defaults.update(kwargs)
    return reconciler.reconcile_cluster(role, **defaults)


# ---------------------------------------------------------------------------
# 1. Healthy no-op
# ---------------------------------------------------------------------------

def test_healthy_cluster_is_a_noop(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=2)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_nodes"] == []
    assert result["recreated_agents"] == []
    assert result["errors"] == []
    assert result["attempts_used"] == 1
    # Never touch healthy objects.
    assert not cluster.apply_calls
    assert not cluster.delete_calls


# ---------------------------------------------------------------------------
# 2. Missing pod recreation
# ---------------------------------------------------------------------------

def test_missing_agent_pod_is_recreated(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=2)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs[:1])  # agent for kwok-node-1 never deployed

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_agents"] == ["mock-cilium-agent-1"]
    assert result["recreated_nodes"] == []
    assert (NAMESPACE, "mock-cilium-agent-1") in cluster.pods


# ---------------------------------------------------------------------------
# 3. Failed / unready pod replacement
# ---------------------------------------------------------------------------

def test_unready_agent_pod_is_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=2)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    # Break agent-0: Failed phase + container not ready.
    key = (NAMESPACE, "mock-cilium-agent-0")
    cluster.pods[key]["status"] = {"phase": "Failed", "containerStatuses": [{"ready": False}]}

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_agents"] == ["mock-cilium-agent-0"]
    assert ("pod", "mock-cilium-agent-0") in cluster.delete_calls
    assert cluster.pods[key]["status"]["phase"] == "Running"


# ---------------------------------------------------------------------------
# 4. Pod hosted on a NotReady real node is replaced
# ---------------------------------------------------------------------------

def test_agent_on_notready_real_node_is_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_real_node("aks-real-bad", ready=False)
    key = (NAMESPACE, "mock-cilium-agent-0")
    cluster.pods[key]["spec"]["nodeName"] = "aks-real-bad"

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_agents"] == ["mock-cilium-agent-0"]
    # Recreated onto the (only) healthy real node.
    assert cluster.pods[key]["spec"]["nodeName"] == HEALTHY_REAL_NODE


def test_agent_identity_drift_is_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    key = (NAMESPACE, "mock-cilium-agent-0")
    cluster.pods[key]["metadata"]["labels"]["app"] = "wrong-app"
    cluster.pods[key]["spec"]["containers"][0]["env"][0]["value"] = "wrong-node"

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_agents"] == ["mock-cilium-agent-0"]
    assert cluster.pods[key]["metadata"]["labels"]["app"] == "mock-cilium-agent"
    assert (
        cluster.pods[key]["spec"]["containers"][0]["env"][0]["value"]
        == "kwok-node-0"
    )


def test_transient_kubectl_failure_is_retried(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    cluster = FakeKubeCluster(transient_get_failures=1)
    cluster.seed(node_docs, agent_docs)

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["attempts_used"] == 2
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# 5. Missing node recreation + forced paired-agent replacement
# ---------------------------------------------------------------------------

def test_missing_node_recreation_forces_paired_agent_replacement(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=2)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    del cluster.nodes["kwok-node-0"]  # simulate the node vanishing (its agent stays healthy)

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_nodes"] == ["kwok-node-0"]
    # The paired agent (mock-cilium-agent-0) is forced to recreate even though it
    # was healthy before the node came back.
    assert "mock-cilium-agent-0" in result["recreated_agents"]
    assert ("pod", "mock-cilium-agent-0") in cluster.delete_calls
    assert "kwok-node-0" in cluster.nodes


# ---------------------------------------------------------------------------
# 6. Unhealthy (drifted / NotReady) node recreation
# ---------------------------------------------------------------------------

def test_unhealthy_node_is_recreated(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.nodes["kwok-node-0"]["status"]["conditions"] = [{"type": "Ready", "status": "False"}]

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_nodes"] == ["kwok-node-0"]
    assert ("node", "kwok-node-0") in cluster.delete_calls
    assert cluster.nodes["kwok-node-0"]["status"]["conditions"] == [{"type": "Ready", "status": "True"}]


# ---------------------------------------------------------------------------
# 7. Extra objects outside the desired manifest => hard failure, no deletion
# ---------------------------------------------------------------------------

def test_extra_objects_are_unsafe_drift_and_fail_without_deleting(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    # An extra KWOK node + mock-agent pod that provision-kwok-layer.sh never generated.
    cluster._apply({  # pylint: disable=protected-access
        "kind": "Node",
        "metadata": {"name": "kwok-node-extra", "labels": {"type": "kwok"}},
        "spec": {},
    })
    cluster._apply({  # pylint: disable=protected-access
        "kind": "Pod",
        "metadata": {
            "name": "mock-cilium-agent-extra",
            "namespace": NAMESPACE,
            "labels": {"app": "mock-cilium-agent", "mock-clustermesh/serves-node": "kwok-node-extra"},
        },
        "spec": {"containers": [{"name": "mock-cilium-agent", "image": IMAGE}]},
    })

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "failed"
    assert any("unsafe drift" in error for error in result["errors"])
    assert any("kwok-node-extra" in error for error in result["errors"])
    assert any("mock-cilium-agent-extra" in error for error in result["errors"])
    # Never silently deleted.
    assert not cluster.delete_calls
    assert "kwok-node-extra" in cluster.nodes
    assert (NAMESPACE, "mock-cilium-agent-extra") in cluster.pods


# ---------------------------------------------------------------------------
# 8. Malformed / missing desired state
# ---------------------------------------------------------------------------

def test_missing_state_dir_fails_cleanly(tmp_path, monkeypatch):
    cluster = FakeKubeCluster()
    result = _reconcile(monkeypatch, cluster, "mesh-absent", tmp_path)

    assert result["status"] == "failed"
    assert result["attempts_used"] == 0
    assert result["errors"]
    assert "missing desired-state metadata" in result["errors"][0]
    # Never touched the cluster at all.
    assert not cluster.apply_calls
    assert not cluster.delete_calls


def test_malformed_metadata_fails_cleanly(tmp_path, monkeypatch):
    role = "mesh-1"
    write_state_dir(tmp_path, role, node_count=1)
    (tmp_path / role / "metadata.json").write_text("{not valid json", encoding="utf-8")
    cluster = FakeKubeCluster()

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "failed"
    assert "invalid desired-state metadata" in result["errors"][0]


def test_orphaned_agent_in_desired_state_fails_cleanly(tmp_path, monkeypatch):
    """agents.yaml serving a node not present in nodes.yaml is malformed desired state."""
    role = "mesh-1"
    state_dir = tmp_path / role
    state_dir.mkdir(parents=True)
    (state_dir / "nodes.yaml").write_text(f"---\n{yaml.safe_dump(_node_doc(0))}", encoding="utf-8")
    agent = _agent_doc(1)  # serves kwok-node-1, which has no matching node doc
    (state_dir / "agents.yaml").write_text(f"---\n{yaml.safe_dump(agent)}", encoding="utf-8")
    (state_dir / "metadata.json").write_text(
        json.dumps({"agent_namespace": NAMESPACE}), encoding="utf-8",
    )
    cluster = FakeKubeCluster()

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "failed"
    assert any("unknown node" in error or "no paired agent" in error for error in result["errors"])


# ---------------------------------------------------------------------------
# 9. Bounded, unresolved failure
# ---------------------------------------------------------------------------

def test_unresolvable_agent_fails_after_bounded_attempts(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, _agent_docs = write_state_dir(tmp_path, role, node_count=1)
    # This agent is recreated every attempt but the fake always brings it back
    # broken (simulates a perpetually crash-looping mock-agent image).
    cluster = FakeKubeCluster(permanently_broken_pods={"mock-cilium-agent-0"})
    cluster.seed(node_docs, [])  # agent never comes up healthy

    result = _reconcile(monkeypatch, cluster, role, tmp_path, attempts=2, settle_seconds=0)

    assert result["status"] == "failed"
    assert result["attempts_used"] == 2
    assert any("exhausted" in error or "unhealthy" in error for error in result["errors"])


# ---------------------------------------------------------------------------
# End-to-end: reconcile_all / main() aggregation across multiple clusters
# ---------------------------------------------------------------------------

def test_reconcile_all_aggregates_ok_and_failed_clusters(tmp_path, monkeypatch):
    ok_role = "mesh-1"
    failed_role = "mesh-2"
    ok_nodes, ok_agents = write_state_dir(tmp_path, ok_role, node_count=1)
    write_state_dir(tmp_path, failed_role, node_count=1)  # left un-seeded => stays missing

    clusters = {
        ok_role: FakeKubeCluster(),
        # failed_role's cluster's agent is permanently broken so it will never
        # converge within the bounded attempt budget.
        failed_role: FakeKubeCluster(permanently_broken_pods={"mock-cilium-agent-0"}),
    }
    clusters[ok_role].seed(ok_nodes, ok_agents)

    def dispatch(cmd, **kwargs):
        # kubeconfig path embeds the role so the dispatcher can route to the
        # right fake cluster instance.
        kubeconfig = cmd[cmd.index("--kubeconfig") + 1]
        role = Path(kubeconfig).stem
        return clusters[role].run(cmd, **kwargs)

    monkeypatch.setattr(reconciler.subprocess, "run", dispatch)

    results = reconciler.reconcile_all(
        [
            {"role": ok_role, "kubeconfig": f"/kube/{ok_role}.config"},
            {"role": failed_role, "kubeconfig": f"/kube/{failed_role}.config"},
        ],
        state_root=str(tmp_path),
        expected_count=None,
        max_concurrent=2,
        attempts=2,
        settle_seconds=0,
        request_timeout_seconds=5,
    )

    by_role = {r["role"]: r for r in results}
    assert by_role[ok_role]["status"] == "ok"
    assert by_role[failed_role]["status"] == "failed"

    summary_file = tmp_path / "summary.json"
    reconciler.write_summary(str(summary_file), {
        "schema_version": 1,
        "total_clusters": len(results),
        "failed_roles": sorted(r["role"] for r in results if r["status"] != "ok"),
        "results": sorted(results, key=lambda r: r["role"]),
    })
    written = json.loads(summary_file.read_text(encoding="utf-8"))
    assert written["failed_roles"] == [failed_role]


# ---------------------------------------------------------------------------
# 10. Exact behavioral identity: additional desired-field drift coverage
# ---------------------------------------------------------------------------

def test_missing_clustermesh_config_arg_is_drift_and_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, agent_doc_fn=_agent_doc_with_clustermesh,
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    key = (NAMESPACE, "mock-cilium-agent-0")
    # Live container is missing the --clustermesh-config arg the desired doc has.
    cluster.pods[key]["spec"]["containers"][0]["args"] = ["--cluster-id=1"]

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_agents"] == ["mock-cilium-agent-0"]
    assert any(
        "--clustermesh-config" in arg
        for arg in cluster.pods[key]["spec"]["containers"][0]["args"]
    )


def test_missing_clustermesh_volume_mount_is_drift_and_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, agent_doc_fn=_agent_doc_with_clustermesh,
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    key = (NAMESPACE, "mock-cilium-agent-0")
    cluster.pods[key]["spec"]["containers"][0]["volumeMounts"] = []

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_agents"] == ["mock-cilium-agent-0"]
    assert cluster.pods[key]["spec"]["containers"][0]["volumeMounts"]


def test_missing_clustermesh_volume_is_drift_and_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, agent_doc_fn=_agent_doc_with_clustermesh,
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    key = (NAMESPACE, "mock-cilium-agent-0")
    cluster.pods[key]["spec"]["volumes"] = []

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_agents"] == ["mock-cilium-agent-0"]
    assert cluster.pods[key]["spec"]["volumes"]


def test_wrong_cluster_id_arg_is_drift_and_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1,
        agent_doc_fn=lambda i: _agent_doc_with_clustermesh(i, cluster_id="1"),
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    key = (NAMESPACE, "mock-cilium-agent-0")
    cluster.pods[key]["spec"]["containers"][0]["args"] = [
        "--cluster-id=2",  # wrong -- desired wants 1
        "--clustermesh-config=/var/lib/cilium/clustermesh/",
    ]

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_agents"] == ["mock-cilium-agent-0"]
    assert "--cluster-id=1" in cluster.pods[key]["spec"]["containers"][0]["args"]


def test_taint_drift_is_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, node_doc_fn=_node_doc_with_taint,
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.nodes["kwok-node-0"]["spec"]["taints"] = []  # taint missing live

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_nodes"] == ["kwok-node-0"]
    assert cluster.nodes["kwok-node-0"]["spec"]["taints"]


def test_podcidrs_drift_is_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.nodes["kwok-node-0"]["spec"]["podCIDRs"] = ["100.9.9.0/24"]  # wrong live CIDR

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_nodes"] == ["kwok-node-0"]
    assert cluster.nodes["kwok-node-0"]["spec"]["podCIDRs"] == ["100.1.0.0/24"]


def test_metadata_annotation_drift_is_replaced(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.nodes["kwok-node-0"]["metadata"]["annotations"]["kwok.x-k8s.io/node"] = "not-fake"

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["recreated_nodes"] == ["kwok-node-0"]
    assert cluster.nodes["kwok-node-0"]["metadata"]["annotations"]["kwok.x-k8s.io/node"] == "fake"


# ---------------------------------------------------------------------------
# 11. ClusterMesh consume-secret reconciliation
# ---------------------------------------------------------------------------

def _seed_clustermesh_sources(cluster, data=None):
    for name, doc in _clustermesh_secret_docs(data=data).items():
        cluster.add_secret(name, reconciler.CLUSTERMESH_SOURCE_NAMESPACE, doc)


def test_missing_target_secrets_are_repaired(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, metadata_overrides={"consume_clustermesh": True},
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    _seed_clustermesh_sources(cluster)
    # No target-namespace copies exist yet -- all four must be created.

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["repaired_secrets"] == sorted(reconciler.CLUSTERMESH_SECRET_NAMES)
    for name in reconciler.CLUSTERMESH_SECRET_NAMES:
        assert (NAMESPACE, name) in cluster.secrets
        assert (
            cluster.secrets[(NAMESPACE, name)]["data"]
            == cluster.secrets[(reconciler.CLUSTERMESH_SOURCE_NAMESPACE, name)]["data"]
        )


def test_drifted_target_secret_is_repaired(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, metadata_overrides={"consume_clustermesh": True},
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    _seed_clustermesh_sources(cluster)
    # Pre-seed all four target copies in sync, except one drifted -- only that
    # one drifted secret should be (re)applied.
    for name, doc in _clustermesh_secret_docs().items():
        cluster.add_secret(name, NAMESPACE, doc)
    drifted_name = reconciler.CLUSTERMESH_SECRET_NAMES[0]
    cluster.secrets[(NAMESPACE, drifted_name)]["data"] = {"placeholder": "d3Jvbmc="}  # "wrong"

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["repaired_secrets"] == [drifted_name]
    assert (
        cluster.secrets[(NAMESPACE, drifted_name)]["data"]
        == cluster.secrets[(reconciler.CLUSTERMESH_SOURCE_NAMESPACE, drifted_name)]["data"]
    )


def test_missing_source_secret_is_hard_failure(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, metadata_overrides={"consume_clustermesh": True},
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    # Seed only 3 of the 4 required kube-system source secrets; the FIRST name
    # (in reconciliation order) is the missing one, so nothing is touched
    # before the hard failure is raised.
    sources = _clustermesh_secret_docs()
    missing_name = reconciler.CLUSTERMESH_SECRET_NAMES[0]
    del sources[missing_name]
    for name, doc in sources.items():
        cluster.add_secret(name, reconciler.CLUSTERMESH_SOURCE_NAMESPACE, doc)

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "failed"
    assert any(missing_name in error and "kube-system" in error for error in result["errors"])
    # Fails immediately -- never attempts any node/agent repair.
    assert result["attempts_used"] == 0
    assert not cluster.apply_calls
    assert not cluster.delete_calls


# ---------------------------------------------------------------------------
# 12. KWOK support-infra reconciliation
# ---------------------------------------------------------------------------

def test_healthy_support_infra_is_noop(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_support_infra()

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert result["repaired_support"] == []
    assert not cluster.apply_calls


def test_missing_apf_objects_are_repaired(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_support_infra(apf=False)

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert any(
        "PriorityLevelConfiguration" in reason or "FlowSchema" in reason
        for reason in result["repaired_support"]
    )
    assert ("prioritylevelconfiguration", None, "kwok-controller") in cluster.existence_objects
    assert ("flowschema", None, "kwok-controller") in cluster.existence_objects


def test_missing_stage_objects_are_repaired(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_support_infra(stage_names=())  # no Stage objects present live

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert any("Stage" in reason for reason in result["repaired_support"])
    assert ("stage", None, "node-fast-ready") in cluster.existence_objects
    assert ("stage", None, "pod-fast-ready") in cluster.existence_objects


def test_missing_rbac_objects_are_repaired(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_support_infra(service_account=False, cluster_role_binding=False)

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert any(
        "ServiceAccount" in reason or "ClusterRoleBinding" in reason
        for reason in result["repaired_support"]
    )
    assert ("serviceaccount", NAMESPACE, SERVICE_ACCOUNT) in cluster.existence_objects
    assert ("clusterrolebinding", None, f"{SERVICE_ACCOUNT}-cluster-admin") in cluster.existence_objects


def test_unavailable_kwok_controller_is_repaired(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_support_infra(deployment_available_replicas=0)

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    assert any("availableReplicas" in reason for reason in result["repaired_support"])
    assert cluster.deployments[("kube-system", "kwok-controller")]["status"]["availableReplicas"] == 1


def test_support_infra_unresolved_failure(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_support_infra(deployment_available_replicas=0)

    # Simulate a stuck rollout: re-applying the Deployment doc never brings the
    # controller back to available (unlike the default fake behavior), so the
    # bounded repair budget must exhaust and fail cleanly.
    original_apply = cluster._apply  # pylint: disable=protected-access

    def _apply_but_keep_controller_down(doc):
        original_apply(doc)
        if doc.get("kind") == "Deployment":
            cluster.deployments[("kube-system", "kwok-controller")]["status"]["availableReplicas"] = 0

    monkeypatch.setattr(cluster, "_apply", _apply_but_keep_controller_down)

    result = _reconcile(monkeypatch, cluster, role, tmp_path, attempts=2, settle_seconds=0)

    assert result["status"] == "failed"
    assert any("availableReplicas" in error or "exhausted" in error for error in result["errors"])


# ---------------------------------------------------------------------------
# 13. --run-id validation (stale role-only state rejection)
# ---------------------------------------------------------------------------

def test_run_id_mismatch_is_rejected_as_stale_state(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, metadata_overrides={"run_id": "run-A"},
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)

    result = _reconcile(monkeypatch, cluster, role, tmp_path, run_id="run-B")

    assert result["status"] == "failed"
    assert any("stale desired state" in error for error in result["errors"])
    assert result["attempts_used"] == 0
    assert not cluster.apply_calls
    assert not cluster.delete_calls


def test_run_id_match_succeeds(tmp_path, monkeypatch):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, metadata_overrides={"run_id": "run-A"},
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)

    result = _reconcile(monkeypatch, cluster, role, tmp_path, run_id="run-A")

    assert result["status"] == "ok"
