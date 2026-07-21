"""Tests for the mock-layer reconciler (mock_layer_reconcile.py).

Uses a small in-memory fake `kubectl` (monkeypatching `subprocess.run` inside the
reconciler module) instead of a real cluster, consistent with how the existing
telemetry-audit tests fake their HTTP layer (see test_clustermesh_telemetry_audit.py).
"""
# pylint: disable=too-many-lines

import importlib.util
import json
import re
import subprocess
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
        self.namespaces = set()  # live Namespace names
        self.existence_objects = set()  # (kind_lower, namespace_or_None, name)
        self.apply_calls = []
        self.delete_calls = []
        self.get_calls = []  # every "get" cmd issued, in order -- proves call batching
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
                           apf=True, service_account=True, cluster_role_binding=True,
                           namespace=True):
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
        if namespace:
            self.namespaces.add(NAMESPACE)
        if service_account:
            self.existence_objects.add(("serviceaccount", NAMESPACE, SERVICE_ACCOUNT))
        if cluster_role_binding:
            self.existence_objects.add(("clusterrolebinding", None, f"{SERVICE_ACCOUNT}-cluster-admin"))

    def seed(self, node_docs, agent_docs):
        for doc in node_docs:
            self._apply(dict(doc))
        for doc in agent_docs:
            self._apply(dict(doc))

    def delete_namespace(self, namespace):
        """Simulate `kubectl delete namespace <namespace>`: real Kubernetes
        cascades this into deleting every namespaced object living inside it
        (ServiceAccounts, Pods, Secrets, ...) -- mirror that here so tests can
        exercise "the whole agent namespace vanished" as a single realistic
        fault instead of only ever deleting one object kind at a time.
        """
        self.namespaces.discard(namespace)
        self.existence_objects = {
            (kind, ns, name) for (kind, ns, name) in self.existence_objects if ns != namespace
        }
        self.pods = {key: pod for key, pod in self.pods.items() if key[0] != namespace}
        self.secrets = {key: secret for key, secret in self.secrets.items() if key[0] != namespace}

    def run(self, cmd, input=None, capture_output=True, text=True,  # pylint: disable=redefined-builtin
             timeout=None, check=False):
        del capture_output, text, timeout, check  # unused; fake honors them implicitly
        if "get" in cmd:
            self.get_calls.append(list(cmd))
        if "get" in cmd and self.transient_get_failures > 0:
            self.transient_get_failures -= 1
            return _failed("transient apiserver error")
        if "get" in cmd and "nodes" in cmd:
            return _completed(json.dumps({"items": list(self.nodes.values())}))
        if "get" in cmd and "pods" in cmd:
            namespace = _namespace_of(cmd)
            items = [pod for (ns, _name), pod in self.pods.items() if ns == namespace]
            return _completed(json.dumps({"items": items}))
        if "get" in cmd and "deployment" in cmd:
            idx = cmd.index("deployment")
            name = cmd[idx + 1]
            namespace = _namespace_of(cmd)
            deployment = self.deployments.get((namespace, name))
            if deployment is None:
                return _failed(f'Error from server (NotFound): deployments.apps "{name}" not found')
            return _completed(json.dumps(deployment))
        if "get" in cmd and "stage" in cmd:
            # kubectl_list_names (via kubectl_list_by_name): ONE true LIST
            # call proving the whole Stage set at once (mirrors
            # `kubectl get stage -o json`, no explicit names).
            items = [
                {"kind": "Stage", "metadata": {"name": name}}
                for (kind, _ns, name) in self.existence_objects if kind == "stage"
            ]
            return _completed(json.dumps({"kind": "StageList", "items": items}))
        if "get" in cmd and "secrets" in cmd:
            # kubectl_list_by_name: ONE true `get secrets -o json` LIST per
            # namespace -- the caller selects its desired names out locally.
            namespace = _namespace_of(cmd)
            items = [secret for (ns, _name), secret in self.secrets.items() if ns == namespace]
            return _completed(json.dumps({"kind": "SecretList", "items": items}))
        if "get" in cmd and "serviceaccounts" in cmd:
            # kubectl_list_by_name: ONE true LIST per desired namespace. Real
            # kubectl 404s a namespaced LIST against a namespace that doesn't
            # exist (e.g. the whole Namespace was deleted) -- mirror that so
            # tests can prove the reconciler skips this call for a missing
            # namespace instead of tripping over the NotFound.
            namespace = _namespace_of(cmd)
            if namespace is not None and namespace not in self.namespaces:
                return _failed(f'Error from server (NotFound): namespaces "{namespace}" not found')
            items = [
                {"kind": "ServiceAccount", "metadata": {"name": name, "namespace": ns}}
                for (kind, ns, name) in self.existence_objects
                if kind == "serviceaccount" and ns == namespace
            ]
            return _completed(json.dumps({"kind": "ServiceAccountList", "items": items}))
        if "get" in cmd and "namespaces" in cmd:
            # kubectl_list_by_name: ONE true cluster-scoped LIST proving the
            # whole desired Namespace set at once (never NotFound-prone --
            # "namespaces" itself is always a valid cluster-scoped resource).
            items = [{"kind": "Namespace", "metadata": {"name": name}} for name in self.namespaces]
            return _completed(json.dumps({"kind": "NamespaceList", "items": items}))
        if "get" in cmd and "clusterrolebindings" in cmd:
            # kubectl_list_by_name: ONE cluster-scoped LIST, never combined
            # with the namespaced ServiceAccount LIST above.
            items = [
                {"kind": "ClusterRoleBinding", "metadata": {"name": name}}
                for (kind, _ns, name) in self.existence_objects if kind == "clusterrolebinding"
            ]
            return _completed(json.dumps({"kind": "ClusterRoleBindingList", "items": items}))
        if "get" in cmd and "prioritylevelconfigurations" in cmd:
            # kubectl_list_by_name: ONE LIST for all PriorityLevelConfigurations.
            items = [
                {"kind": "PriorityLevelConfiguration", "metadata": {"name": name}}
                for (kind, _ns, name) in self.existence_objects if kind == "prioritylevelconfiguration"
            ]
            return _completed(json.dumps({"kind": "PriorityLevelConfigurationList", "items": items}))
        if "get" in cmd and "flowschemas" in cmd:
            # kubectl_list_by_name: ONE LIST for all FlowSchemas.
            items = [
                {"kind": "FlowSchema", "metadata": {"name": name}}
                for (kind, _ns, name) in self.existence_objects if kind == "flowschema"
            ]
            return _completed(json.dumps({"kind": "FlowSchemaList", "items": items}))
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
            self.namespaces.add(name)
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


def test_deleted_agent_namespace_is_repaired_before_secrets_and_agents(tmp_path, monkeypatch):
    """Deleting the WHOLE agent Namespace (as `kubectl delete namespace` would,
    cascading away its ServiceAccount, agent Pods, and consume-path Secret
    copies) must be repaired, not treated as a hard failure: the persisted
    RBAC manifest (Namespace+ServiceAccount+ClusterRoleBinding) is re-applied
    as recoverable support drift, and only once that succeeds do the
    consume secrets and agent Pods -- which also depended on that namespace
    existing -- get repaired in turn.
    """
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, metadata_overrides={"consume_clustermesh": True},
    )
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_support_infra()
    _seed_clustermesh_sources(cluster)
    for name, doc in _clustermesh_secret_docs().items():
        cluster.add_secret(name, NAMESPACE, doc)

    # Simulate the whole agent namespace vanishing: cascades away its
    # ServiceAccount, agent Pod, and target Secret copies, exactly like a
    # real `kubectl delete namespace mock-clustermesh` would.
    cluster.delete_namespace(NAMESPACE)
    assert NAMESPACE not in cluster.namespaces
    assert (NAMESPACE, "mock-cilium-agent-0") not in cluster.pods
    assert not any(ns == NAMESPACE for ns, _name in cluster.secrets)
    assert ("serviceaccount", NAMESPACE, SERVICE_ACCOUNT) not in cluster.existence_objects

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "ok"
    # The missing Namespace was recorded as recoverable support drift (never
    # an unhandled NotFound exception) and repaired.
    assert any("Namespace" in reason for reason in result["repaired_support"])
    assert NAMESPACE in cluster.namespaces
    assert ("serviceaccount", NAMESPACE, SERVICE_ACCOUNT) in cluster.existence_objects
    # Only once the namespace exists again can the secrets/agents that
    # depend on it be repaired.
    assert result["repaired_secrets"] == sorted(reconciler.CLUSTERMESH_SECRET_NAMES)
    assert result["recreated_agents"] == ["mock-cilium-agent-0"]

    # Support-infra repair (which restores the Namespace itself) runs, and
    # completes, before any Secret/Pod is (re)applied.
    kinds_applied = [doc["kind"] for doc in cluster.apply_calls]
    assert kinds_applied.index("Namespace") < kinds_applied.index("Secret")
    assert kinds_applied.index("Namespace") < kinds_applied.index("Pod")


def test_namespace_list_api_failure_is_hard_failure_not_swallowed_as_drift(tmp_path, monkeypatch):
    """A genuine failure of the (always cluster-scoped, never NotFound-prone)
    Namespace LIST call itself -- e.g. an apiserver outage -- must still
    raise/fail closed, never be silently treated as recoverable "missing
    Namespace" support drift.
    """
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_support_infra()

    original_run = cluster.run

    def _run_with_broken_namespace_list(cmd, **kwargs):
        if "get" in cmd and "namespaces" in cmd:
            return _failed("Error from server: etcdserver: request timed out")
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(cluster, "run", _run_with_broken_namespace_list)

    result = _reconcile(monkeypatch, cluster, role, tmp_path, attempts=2, settle_seconds=0)

    assert result["status"] == "failed"
    assert any("request timed out" in error for error in result["errors"])
    # Never silently treated as recoverable drift -- no RBAC re-apply attempted.
    assert not cluster.apply_calls



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


# ---------------------------------------------------------------------------
# 14. Batched kubectl reads (build 74186 fix) -- proves the ~20 serial
#     object-by-object probes per cluster were collapsed into a small,
#     size-independent number of round trips.
# ---------------------------------------------------------------------------

def test_support_infra_check_uses_a_fixed_small_number_of_kubectl_calls(tmp_path, monkeypatch):
    """Regardless of how many Stage/APF/RBAC objects are desired, verifying
    support-infra health must cost a FIXED small number of kubectl calls --
    one true LIST per resource type/namespace (deployment-get, stage-list,
    prioritylevelconfigurations-list, flowschemas-list, namespaces-list,
    serviceaccounts-list, clusterrolebindings-list) -- never one existence
    probe (or one apiserver-side GET per name packed into a single kubectl
    invocation) per object, which is what previously drove ~8-10 serial calls
    per cluster per attempt and contributed to build 74186's outer-timeout
    kill (rc=124).
    """
    role = "mesh-1"
    write_state_dir(tmp_path, role, node_count=1)
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.add_support_infra()  # fully healthy: 2 stage + 2 apf + namespace + SA + CRB
    monkeypatch.setattr(reconciler.subprocess, "run", cluster.run)

    desired = reconciler.load_desired_state(str(tmp_path / role))
    healthy, problems = reconciler.support_infra_is_healthy(
        f"/kube/{role}.config", desired, timeout_seconds=5,
    )

    assert healthy
    assert not problems
    # 1 deployment get + 1 stage list + 1 prioritylevelconfigurations list +
    # 1 flowschemas list + 1 namespaces list + 1 serviceaccounts list +
    # 1 clusterrolebindings list.
    assert len(cluster.get_calls) == 7


def test_support_infra_check_call_count_is_independent_of_object_count(tmp_path, monkeypatch):
    """Adding MORE desired Stage objects must not add MORE kubectl calls --
    the whole set is still proved with the same single list call."""
    role = "mesh-1"
    write_state_dir(tmp_path, role, node_count=1)
    many_stage_docs = [
        {"apiVersion": "kwok.x-k8s.io/v1alpha1", "kind": "Stage", "metadata": {"name": f"stage-{i}"}}
        for i in range(10)
    ]
    write_support_manifests(tmp_path, role, stage=many_stage_docs)
    cluster = FakeKubeCluster()
    cluster.add_support_infra(stage_names=tuple(f"stage-{i}" for i in range(10)))
    monkeypatch.setattr(reconciler.subprocess, "run", cluster.run)

    desired = reconciler.load_desired_state(str(tmp_path / role))
    healthy, problems = reconciler.support_infra_is_healthy(
        f"/kube/{role}.config", desired, timeout_seconds=5,
    )

    assert healthy
    assert not problems
    assert len(cluster.get_calls) == 7  # same fixed count as the 2-Stage case above


def test_secrets_reconcile_uses_two_batched_kubectl_calls(tmp_path, monkeypatch):
    """4 source + 4 target secret gets must collapse into exactly 2 true
    `get secrets -o json` LIST calls (one per namespace) instead of 8
    individual `get secret <name>` invocations."""
    role = "mesh-1"
    write_state_dir(tmp_path, role, node_count=1)
    cluster = FakeKubeCluster()
    _seed_clustermesh_sources(cluster)
    monkeypatch.setattr(reconciler.subprocess, "run", cluster.run)

    repaired = reconciler.reconcile_clustermesh_secrets(
        f"/kube/{role}.config", NAMESPACE, timeout_seconds=5,
    )

    assert repaired == sorted(reconciler.CLUSTERMESH_SECRET_NAMES)
    assert len(cluster.get_calls) == 2


def test_kubectl_list_by_name_keys_objects_by_name_and_validates_list_shape(monkeypatch):
    """Direct unit test for kubectl_list_by_name's real kubectl LIST response
    shape: ONE `kubectl get <resource> -o json` call always returns
    {"kind": "<Resource>List", "items": [...]}, never a bare object and
    never one entry per explicitly-named ref -- this is what makes it a true
    server-side LIST (one apiserver round trip) rather than N GETs disguised
    as a single kubectl invocation.
    """
    calls = []

    def fake_run(cmd, input=None, capture_output=True, text=True,  # pylint: disable=redefined-builtin
                 timeout=None, check=False):
        del input, capture_output, text, timeout, check
        calls.append(list(cmd))
        return _completed(json.dumps({
            "kind": "ServiceAccountList",
            "items": [
                {"kind": "ServiceAccount", "metadata": {"name": "sa-1"}},
                {"kind": "ServiceAccount", "metadata": {"name": "sa-2"}},
            ],
        }))

    monkeypatch.setattr(reconciler.subprocess, "run", fake_run)

    result = reconciler.kubectl_list_by_name(
        "/kube/mesh-1.config", "serviceaccounts", timeout_seconds=5,
    )

    assert set(result) == {"sa-1", "sa-2"}
    assert result["sa-1"] == {"kind": "ServiceAccount", "metadata": {"name": "sa-1"}}
    # Exactly ONE kubectl invocation regardless of how many names are desired.
    assert len(calls) == 1


def test_kubectl_list_by_name_handles_empty_list(monkeypatch):
    """An empty LIST (no live objects of this resource type) must return an
    empty mapping, not raise -- callers then treat every desired name as
    missing via a plain local membership check."""
    def fake_run(cmd, input=None, capture_output=True, text=True,  # pylint: disable=redefined-builtin
                 timeout=None, check=False):
        del cmd, input, capture_output, text, timeout, check
        return _completed(json.dumps({"kind": "StageList", "items": []}))

    monkeypatch.setattr(reconciler.subprocess, "run", fake_run)

    result = reconciler.kubectl_list_by_name("/kube/mesh-1.config", "stage", timeout_seconds=5)
    assert not result


def test_kubectl_list_by_name_rejects_non_list_shape(monkeypatch):
    """A malformed/unexpected response missing a usable 'items' list must
    fail closed with ReconcileError rather than silently treating every
    desired name as missing."""
    def fake_run(cmd, input=None, capture_output=True, text=True,  # pylint: disable=redefined-builtin
                 timeout=None, check=False):
        del cmd, input, capture_output, text, timeout, check
        return _completed(json.dumps({"kind": "ServiceAccount", "metadata": {"name": "sa-1"}}))

    monkeypatch.setattr(reconciler.subprocess, "run", fake_run)

    try:
        reconciler.kubectl_list_by_name("/kube/mesh-1.config", "serviceaccounts", timeout_seconds=5)
    except reconciler.ReconcileError as exc:
        assert "serviceaccounts" in str(exc)
    else:
        raise AssertionError("expected ReconcileError for a non-List response shape")


def test_multiple_missing_source_secrets_are_reported_together(tmp_path, monkeypatch):
    """Extends the single-missing-source-secret hard-failure case: when
    SEVERAL source secrets are simultaneously missing, the batched multi-get
    must still surface every missing name in one error rather than only the
    first, and must still fail closed without touching anything.
    """
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, metadata_overrides={"consume_clustermesh": True},
    )
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    sources = _clustermesh_secret_docs()
    missing_names = sorted(reconciler.CLUSTERMESH_SECRET_NAMES)[:2]
    for name in missing_names:
        del sources[name]
    for name, doc in sources.items():
        cluster.add_secret(name, reconciler.CLUSTERMESH_SOURCE_NAMESPACE, doc)

    result = _reconcile(monkeypatch, cluster, role, tmp_path)

    assert result["status"] == "failed"
    assert any(all(name in error for name in missing_names) for error in result["errors"])
    assert result["attempts_used"] == 0
    assert not cluster.apply_calls
    assert not cluster.delete_calls


# ---------------------------------------------------------------------------
# 15. Flushed per-phase progress logging (build 74186 diagnosability fix)
# ---------------------------------------------------------------------------

def test_progress_lines_are_emitted_per_phase_without_secret_data(tmp_path, monkeypatch, capsys):
    role = "mesh-1"
    node_docs, agent_docs = write_state_dir(
        tmp_path, role, node_count=1, metadata_overrides={"consume_clustermesh": True},
    )
    write_support_manifests(tmp_path, role)
    cluster = FakeKubeCluster()
    cluster.seed(node_docs, agent_docs)
    cluster.add_support_infra()
    _seed_clustermesh_sources(cluster)

    result = _reconcile(monkeypatch, cluster, role, tmp_path)
    assert result["status"] == "ok"

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith(f"mock-layer-reconcile[{role}]")]
    phases = [line.split("] ", 1)[1].split(":", 1)[0] for line in lines]

    for expected_phase in ("desired-state", "support", "secrets", "inventory", "plan", "convergence", "done"):
        assert expected_phase in phases, f"missing progress line for phase {expected_phase!r}: {lines}"

    # Never leak actual secret values/data -- only counts/names of the fixed,
    # non-sensitive CLUSTERMESH_SECRET_NAMES may appear.
    for secret_doc in _clustermesh_secret_docs().values():
        for value in secret_doc["data"].values():
            assert value not in out


def test_progress_lines_are_flushed_immediately(capsys):
    """`_progress` must flush explicitly rather than relying on line
    buffering -- exactly the buffering gap that made build 74186's timeout
    kill look like "no output at all" even though real work had happened.
    """
    reconciler._progress("mesh-1", "phase-x", "message-y")  # pylint: disable=protected-access
    out = capsys.readouterr().out
    assert out == "mock-layer-reconcile[mesh-1] phase-x: message-y\n"


# ---------------------------------------------------------------------------
# 16. Incremental/atomic summary writing (build 74186 diagnosability fix)
# ---------------------------------------------------------------------------

def test_build_summary_marks_partial_when_roles_are_still_pending():
    args = types.SimpleNamespace(state_root="/state", run_id="run-A", expected_mock_count=2)
    finished = [{"role": "mesh-1", "status": "ok", "errors": []}]

    partial_summary = reconciler._build_summary(  # pylint: disable=protected-access
        args, finished, pending_roles=["mesh-2"],
    )

    assert partial_summary["partial"] is True
    assert partial_summary["success"] is False  # can't be success while anything is still pending
    assert partial_summary["pending_roles"] == ["mesh-2"]
    assert partial_summary["healthy_count"] == 1
    assert partial_summary["total_clusters"] == 2  # 1 finished + 1 pending


def test_build_summary_final_write_has_no_pending_roles_and_reflects_failures():
    args = types.SimpleNamespace(state_root="/state", run_id="run-A", expected_mock_count=2)
    finished = [
        {"role": "mesh-1", "status": "ok", "errors": []},
        {"role": "mesh-2", "status": "failed", "errors": ["boom"]},
    ]

    final_summary = reconciler._build_summary(args, finished, pending_roles=[])  # pylint: disable=protected-access

    assert final_summary["partial"] is False
    assert final_summary["success"] is False
    assert final_summary["pending_roles"] == []
    assert final_summary["failed_roles"] == ["mesh-2"]
    assert final_summary["healthy_count"] == 1
    assert final_summary["failed_count"] == 1


def test_reconcile_all_on_result_callback_writes_incremental_progress(tmp_path, monkeypatch):
    """Proves reconcile_all's on_result hook -- what main() uses to persist a
    partial summary after EVERY cluster, not just at the very end -- fires
    once per completed cluster with a strictly shrinking pending_roles set,
    so a process killed mid-run always leaves behind an accurate partial
    summary instead of nothing (build 74186's original failure mode)."""
    roles = ["mesh-1", "mesh-2"]
    clusters = []
    fakes = {}
    for role in roles:
        node_docs, agent_docs = write_state_dir(tmp_path, role, node_count=1)
        cluster = FakeKubeCluster()
        cluster.seed(node_docs, agent_docs)
        fakes[role] = cluster
        clusters.append({"role": role, "kubeconfig": f"/kube/{role}.config"})

    def fake_subprocess_run(cmd, **kwargs):
        # Route each call to the fake matching the invoked --kubeconfig.
        role = None
        if "--kubeconfig" in cmd:
            kubeconfig = cmd[cmd.index("--kubeconfig") + 1]
            role = Path(kubeconfig).stem
        return fakes[role].run(cmd, **kwargs)

    monkeypatch.setattr(reconciler.subprocess, "run", fake_subprocess_run)

    calls = []

    def on_result(result, results_so_far, pending_roles):
        calls.append((result["role"], len(results_so_far), tuple(pending_roles)))

    results = reconciler.reconcile_all(
        clusters,
        state_root=str(tmp_path),
        expected_count=None,
        max_concurrent=1,  # deterministic single-threaded completion order
        attempts=3,
        settle_seconds=0,
        request_timeout_seconds=5,
        on_result=on_result,
    )

    assert len(results) == 2
    assert all(r["status"] == "ok" for r in results)
    assert len(calls) == 2
    # First callback: one cluster done, the other still pending.
    assert calls[0][1] == 1
    assert calls[0][2] == ("mesh-2",) or calls[0][0] == "mesh-2"
    # Final callback: both done, nothing pending.
    assert calls[1][1] == 2
    assert calls[1][2] == ()


# ---------------------------------------------------------------------------
# 17. execute.yml outer-timeout budget (build 74186 fix)
# ---------------------------------------------------------------------------

EXECUTE_YML_PATH = (
    Path(__file__).resolve().parents[3]
    / "steps"
    / "engine"
    / "clusterloader2"
    / "clustermesh-scale"
    / "execute.yml"
)


def _extract_bash_function(script_text, func_name):
    """Pull one `func_name() { ... }` block out of the embedded execute.yml
    bash script by matching its closing brace at the SAME indentation as its
    opening line -- avoids having to source (and thus execute) the entire
    multi-thousand-line orchestration script just to unit-test one function.
    """
    match = re.search(
        rf"^([ \t]*){re.escape(func_name)}\(\)\s*\{{\n(.*?\n)\1\}}\n",
        script_text,
        re.DOTALL | re.MULTILINE,
    )
    assert match, f"could not find function {func_name!r} in execute.yml"
    return match.group(0)


def _load_execute_yml_script():
    with open(EXECUTE_YML_PATH, "r", encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)
    return doc["steps"][1]["script"]


def _run_budget_function(func_names, call, env):
    script_text = _load_execute_yml_script()
    functions_src = "".join(_extract_bash_function(script_text, name) for name in func_names)
    bash_script = "#!/bin/bash\nset -eo pipefail\n" + functions_src + f"\n{call}\n"
    full_env = dict(env)
    proc = subprocess.run(  # pylint: disable=subprocess-run-check
        ["bash", "-c", bash_script],
        capture_output=True, text=True, timeout=10, env=full_env,
    )
    assert proc.returncode == 0, f"bash function invocation failed: {proc.stderr}"
    return proc.stdout.strip()


def test_mock_reconcile_budget_is_300s_below_50_clusters():
    out = _run_budget_function(
        ["scenario_mock_reconcile_budget_seconds"],
        "cluster_count=2 scenario_mock_reconcile_budget_seconds",
        env={"PATH": "/usr/bin:/bin", "CL2_MOCK_MODE": "true"},
    )
    assert out == "300"


def test_mock_reconcile_budget_is_600s_at_or_above_50_clusters():
    out = _run_budget_function(
        ["scenario_mock_reconcile_budget_seconds"],
        "cluster_count=50 scenario_mock_reconcile_budget_seconds",
        env={"PATH": "/usr/bin:/bin", "CL2_MOCK_MODE": "true"},
    )
    assert out == "600"


def test_mock_reconcile_budget_is_zero_outside_mock_mode():
    out = _run_budget_function(
        ["scenario_mock_reconcile_budget_seconds"],
        "cluster_count=2 scenario_mock_reconcile_budget_seconds",
        env={"PATH": "/usr/bin:/bin", "CL2_MOCK_MODE": "false"},
    )
    assert out == "0"


def test_scenario_post_budget_seconds_reflects_bumped_mock_reconcile_budget():
    """Proves the 300s bump propagates automatically through
    scenario_post_budget_seconds (the shared "protected budget" accounting)
    rather than needing every caller updated separately."""
    out = _run_budget_function(
        [
            "scenario_quiet_window_seconds",
            "scenario_artifact_budget_seconds",
            "scenario_diag_budget_seconds",
            "scenario_mock_reconcile_budget_seconds",
            "scenario_cleanup_reconcile_budget_seconds",
            "scenario_post_budget_seconds",
        ],
        'cluster_count=2 scenario_post_budget_seconds "generic-scenario"',
        env={
            "PATH": "/usr/bin:/bin",
            "CL2_MOCK_MODE": "true",
            "CL2_SHARE_INFRA_SETTLE_SECONDS": "60",
            "CL2_HEALTH_GATE_TIMEOUT_BUFFER_SECONDS": "900",
        },
    )
    # quiet(60) + buffer(900) + artifact(600) + diag(300) + mock_reconcile(300) + cleanup(120) = 2280
    assert out == "2280"


def test_run_mock_layer_reconcile_timeout_fallback_is_syntactically_wired():
    """Static assertion that the rc=124/137 fallback summary logic exists and
    references the required fields -- the full function also invokes a real
    `python3`/`timeout` subprocess, so it is validated statically here rather
    than executed end-to-end (that behavior is exercised by the Python-side
    _build_summary/on_result tests above, which cover the same JSON shape)."""
    script_text = _load_execute_yml_script()
    function_src = _extract_bash_function(script_text, "run_mock_layer_reconcile")

    assert '"$_rc" -eq 124' in function_src
    assert '"$_rc" -eq 137' in function_src
    assert ".success = false" in function_src or "success: false" in function_src
    assert ".timed_out = true" in function_src or "timed_out: true" in function_src
    assert "phase" in function_src
    assert "mock-layer-reconcile[<role>] phase:" in function_src
