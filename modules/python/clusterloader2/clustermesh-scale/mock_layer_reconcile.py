#!/usr/bin/env python3
"""Reconcile the KWOK + mock-cilium-agent mock layer against its persisted desired state.

`provision-kwok-layer.sh` (scenarios/perf-eval/clustermesh-scale/mock/) can persist the
EXACT KWOK Node + mock-cilium-agent Pod manifests it generated for a cluster into
MOCK_STATE_DIR (see deploy-mock-layer.yml, which sets one per cluster role under
$HOME/.kube/mock-layer-state/<role>). This module is a bounded, best-effort repair
pass over that already-deployed layer: for each cluster it loads the persisted
desired manifests, inspects the live KWOK Nodes and mock-cilium-agent Pods via
kubectl, and repairs ONLY the deterministic objects the manifests describe.

It deliberately does much less than a general controller:
  * It never touches anything outside the exact desired Node/Pod names it loaded.
  * It never deletes an object it cannot account for in the desired manifests --
    any such "extra" object is unsafe drift and fails that cluster's reconcile
    rather than being silently removed.
  * It only recreates/repairs; it does not re-derive desired state (podCIDR
    scheme, cluster identity, inherited cilium-config, ...) -- that derivation
    happens once, in provision-kwok-layer.sh, at persist time.

Exit code is 0 iff every cluster converges to a healthy, exact, 1:1 state within
the bounded attempt budget; 1 otherwise. A structured JSON summary (schema_version,
per-cluster repairs/errors) is always written atomically to --summary-file.
"""
# pylint: disable=too-many-lines

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import yaml


NODE_LABEL_SELECTOR = "type=kwok"
AGENT_LABEL_SELECTOR = "app=mock-cilium-agent"
SERVES_NODE_LABEL = "mock-clustermesh/serves-node"
KWOK_NODE_ANNOTATION_KEY = "kwok.x-k8s.io/node"
KWOK_NODE_TYPE_LABEL_VALUE = "kwok"
CONTROLLER_OWNED_NODE_ANNOTATIONS = {
    # The Kubernetes node lifecycle controller rewrites this legacy annotation
    # (AKS currently changes "0" to "15"). It is not mock identity and must
    # never trigger Node recreation.
    "node.alpha.kubernetes.io/ttl",
}

# The four clustermesh client secrets provision-kwok-layer.sh copies from
# kube-system into the agent namespace when CONSUME_CLUSTERMESH is active (see
# STEP 2.5 there). Order matches the provision script for readability only --
# reconciliation treats them independently.
CLUSTERMESH_SOURCE_NAMESPACE = "kube-system"
CLUSTERMESH_SECRET_NAMES = (
    "cilium-clustermesh",
    "clustermesh-apiserver-remote-cert",
    "clustermesh-apiserver-local-cert",
    "cilium-root-ca.crt",
)

# The four already-rendered KWOK support manifests provision-kwok-layer.sh
# persists (verbatim, never re-derived) alongside nodes.yaml/agents.yaml when
# MOCK_STATE_DIR is set. Keys match the "support" sub-dict this module builds
# in DesiredState.support_manifests.
SUPPORT_MANIFEST_FILES = {
    "kwok_controller": "kwok-controller.yaml",
    "stage": "stage-fast.yaml",
    "apf": "kwok-apf.yaml",
    "rbac": "rbac.yaml",
}


class ReconcileError(Exception):
    """An expected, per-cluster reconciliation failure (bad state, kubectl error, ...).

    Deliberately distinct from unexpected exceptions (KeyError, TypeError, ...) that
    would indicate a bug in this tool -- those are allowed to propagate rather than
    being swallowed, per the "no broad exception swallowing" requirement.
    """


class UnsafeSourceSecretMissing(ReconcileError):
    """A required clustermesh SOURCE secret is absent from kube-system.

    Distinct from a generic ReconcileError so callers can fail the cluster
    immediately (no point retrying: the source secret will not appear on its
    own) rather than spending the bounded repair-attempt budget on it.
    """


@dataclass
class DesiredState:
    """The exact desired Nodes/Pods loaded from a cluster's persisted state dir."""

    namespace: str
    node_docs: Dict[str, dict]
    agent_docs: Dict[str, dict]
    agent_for_node: Dict[str, str]  # node name -> serving agent name
    metadata: dict
    # Persisted KWOK support manifests (kwok-controller/stage/apf/rbac), keyed as
    # SUPPORT_MANIFEST_FILES, each value a list of raw YAML docs. None when the
    # persisted state predates support-manifest persistence (no "support/" dir) --
    # support-infra reconciliation is then skipped entirely (back-compat no-op).
    support_manifests: Optional[Dict[str, List[dict]]] = None


@dataclass
class ReconcilePlan:
    """What this attempt needs to do to converge toward the desired state."""

    nodes_to_recreate: List[str] = field(default_factory=list)
    agents_to_recreate: List[str] = field(default_factory=list)
    extra_nodes: List[str] = field(default_factory=list)
    extra_agents: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Desired-state loading
# ---------------------------------------------------------------------------

def _load_multidoc_yaml(path: str) -> List[dict]:
    """Load every non-null document from a persisted multi-kind support manifest.

    Unlike `_load_yaml_docs`, this does not filter by a single expected `kind` --
    the four support manifest files each legitimately mix kinds (e.g. rbac.yaml
    has a Namespace + ServiceAccount + ClusterRoleBinding).
    """
    if not os.path.isfile(path):
        raise ReconcileError(f"missing persisted support manifest: {path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            docs = [doc for doc in yaml.safe_load_all(handle) if doc is not None]
    except yaml.YAMLError as exc:
        raise ReconcileError(f"invalid YAML in {path}: {exc}") from exc
    for doc in docs:
        if not isinstance(doc, dict):
            raise ReconcileError(f"malformed document in {path}: expected a mapping")
    if not docs:
        raise ReconcileError(f"no documents found in {path}")
    return docs


def _find_doc(docs: List[dict], kind: str) -> Optional[dict]:
    for doc in docs:
        if doc.get("kind") == kind:
            return doc
    return None


def _load_yaml_docs(path: str, expected_kind: str) -> Dict[str, dict]:
    if not os.path.isfile(path):
        raise ReconcileError(f"missing desired-state manifest: {path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw_docs = list(yaml.safe_load_all(handle))
    except yaml.YAMLError as exc:
        raise ReconcileError(f"invalid YAML in {path}: {exc}") from exc

    docs: Dict[str, dict] = {}
    for doc in raw_docs:
        if doc is None:
            continue
        if not isinstance(doc, dict):
            raise ReconcileError(f"malformed document in {path}: expected a mapping")
        if doc.get("kind") != expected_kind:
            raise ReconcileError(
                f"malformed document in {path}: expected kind={expected_kind}, "
                f"got {doc.get('kind')!r}"
            )
        doc_metadata = doc.get("metadata")
        name = doc_metadata.get("name") if isinstance(doc_metadata, dict) else None
        if not name:
            raise ReconcileError(f"malformed document in {path}: missing metadata.name")
        if name in docs:
            raise ReconcileError(f"malformed document in {path}: duplicate name {name!r}")
        docs[name] = doc
    if not docs:
        raise ReconcileError(f"no {expected_kind} documents found in {path}")
    return docs


def load_desired_state(state_dir: str) -> DesiredState:
    """Load the persisted desired manifests + metadata for one cluster.

    Raises ReconcileError (never a raw exception) on any missing file, invalid
    YAML/JSON, or structurally malformed desired state, so callers can record a
    clean per-cluster failure instead of crashing the whole reconcile run.
    """
    metadata_path = os.path.join(state_dir, "metadata.json")
    nodes_path = os.path.join(state_dir, "nodes.yaml")
    agents_path = os.path.join(state_dir, "agents.yaml")

    if not os.path.isfile(metadata_path):
        raise ReconcileError(f"missing desired-state metadata: {metadata_path}")
    try:
        with open(metadata_path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconcileError(f"invalid desired-state metadata {metadata_path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ReconcileError(
            f"invalid desired-state metadata {metadata_path}: expected a JSON object"
        )

    namespace = metadata.get("agent_namespace")
    if not isinstance(namespace, str) or not namespace:
        raise ReconcileError(
            f"desired-state metadata {metadata_path} missing 'agent_namespace'"
        )

    node_docs = _load_yaml_docs(nodes_path, "Node")
    agent_docs = _load_yaml_docs(agents_path, "Pod")

    agent_for_node: Dict[str, str] = {}
    for agent_name, doc in agent_docs.items():
        doc_metadata = doc.get("metadata") or {}
        labels = doc_metadata.get("labels") if isinstance(doc_metadata, dict) else None
        served = labels.get(SERVES_NODE_LABEL) if isinstance(labels, dict) else None
        if not served:
            raise ReconcileError(
                f"agent {agent_name!r} in {agents_path} missing '{SERVES_NODE_LABEL}' label"
            )
        if served in agent_for_node:
            raise ReconcileError(
                f"desired state {agents_path} has more than one agent serving node "
                f"{served!r} ({agent_for_node[served]!r} and {agent_name!r})"
            )
        agent_for_node[served] = agent_name

    missing_agents = sorted(set(node_docs) - set(agent_for_node))
    if missing_agents:
        raise ReconcileError(
            f"desired state has node(s) with no paired agent in {agents_path}: {missing_agents}"
        )
    orphan_agents = sorted(set(agent_for_node) - set(node_docs))
    if orphan_agents:
        raise ReconcileError(
            f"desired state has agent(s) serving unknown node(s) in {agents_path}: {orphan_agents}"
        )

    # Persisted KWOK support manifests are optional (a "support/" sub-dir):
    # absent entirely means this state dir predates support-manifest
    # persistence (or a hand-built test fixture that doesn't need it) -- skip
    # support-infra reconciliation rather than failing. If the directory
    # exists, all four files are required (a partial support/ dir is
    # malformed desired state, same as a partial nodes/agents pair would be).
    support_dir = os.path.join(state_dir, "support")
    support_manifests: Optional[Dict[str, List[dict]]] = None
    if os.path.isdir(support_dir):
        support_manifests = {
            key: _load_multidoc_yaml(os.path.join(support_dir, filename))
            for key, filename in SUPPORT_MANIFEST_FILES.items()
        }

    return DesiredState(
        namespace=namespace,
        node_docs=node_docs,
        agent_docs=agent_docs,
        agent_for_node=agent_for_node,
        metadata=metadata,
        support_manifests=support_manifests,
    )


# ---------------------------------------------------------------------------
# Diagnostic progress logging
# ---------------------------------------------------------------------------

def _progress(role: str, phase: str, message: str) -> None:
    """Emit one flushed diagnostic line for `role`'s reconciliation.

    Printed with flush=True rather than relying on line-buffering -- Python
    switches stdout to full block-buffering (not line-buffering) whenever it
    isn't attached to a tty, which is exactly the case when this script's
    stdout is captured into an ADO pipeline log. Without an explicit flush,
    an outer `timeout` SIGTERM/SIGKILL can reap this process with useful
    progress sitting in an unflushed buffer, leaving the log looking like
    nothing happened at all (the original failure mode this addresses).
    Never includes secret data/values -- only counts/names of the fixed,
    non-sensitive CLUSTERMESH_SECRET_NAMES.
    """
    print(f"mock-layer-reconcile[{role}] {phase}: {message}", flush=True)


# ---------------------------------------------------------------------------
# kubectl plumbing -- bounded subprocess timeouts, no shell, no broad excepts.
# ---------------------------------------------------------------------------

def _base_cmd(kubeconfig: str, timeout_seconds: float, namespace: Optional[str] = None) -> List[str]:
    cmd = ["kubectl", "--kubeconfig", kubeconfig, f"--request-timeout={timeout_seconds}s"]
    if namespace:
        cmd += ["-n", namespace]
    return cmd


def _run_kubectl(cmd: List[str], timeout_seconds: float, input_text: Optional[str] = None) -> str:
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReconcileError(
            f"kubectl timed out after {timeout_seconds}s: {' '.join(cmd)}"
        ) from exc
    except OSError as exc:
        raise ReconcileError(f"failed to run kubectl: {' '.join(cmd)}: {exc}") from exc
    if result.returncode != 0:
        raise ReconcileError(
            f"kubectl failed (rc={result.returncode}): {' '.join(cmd)}: {result.stderr.strip()}"
        )
    return result.stdout


def kubectl_get_json(kubeconfig, resource_args, timeout_seconds, namespace=None) -> dict:
    cmd = _base_cmd(kubeconfig, timeout_seconds, namespace) + ["get", *resource_args, "-o", "json"]
    stdout = _run_kubectl(cmd, timeout_seconds)
    try:
        return json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ReconcileError(
            f"kubectl returned invalid JSON for: {' '.join(cmd)}: {exc}"
        ) from exc


def kubectl_apply_doc(kubeconfig, doc, timeout_seconds, namespace=None) -> None:
    kubectl_apply_docs(kubeconfig, [doc], timeout_seconds, namespace=namespace)


def kubectl_apply_docs(kubeconfig, docs, timeout_seconds, namespace=None) -> None:
    docs = list(docs)
    if not docs:
        return
    cmd = _base_cmd(kubeconfig, timeout_seconds, namespace) + ["apply", "-f", "-"]
    manifest = yaml.safe_dump_all(
        docs,
        default_flow_style=False,
        explicit_start=True,
    )
    _run_kubectl(cmd, timeout_seconds, input_text=manifest)


def kubectl_delete(kubeconfig, kind, name, timeout_seconds, namespace=None) -> None:
    kubectl_delete_many(
        kubeconfig,
        kind,
        [name],
        timeout_seconds,
        namespace=namespace,
    )


def kubectl_delete_many(
    kubeconfig, kind, names, timeout_seconds, namespace=None,
) -> None:
    names = list(names)
    if not names:
        return
    cmd = _base_cmd(kubeconfig, timeout_seconds, namespace) + [
        "delete", kind, *names, "--ignore-not-found=true",
        f"--timeout={timeout_seconds}s",
    ]
    if kind == "pod":
        cmd += ["--grace-period=0", "--force"]
    _run_kubectl(cmd, timeout_seconds + 5)


def kubectl_list_by_name(kubeconfig, resource, timeout_seconds, namespace=None) -> Dict[str, dict]:
    """List every live object of `resource` in ONE true Kubernetes LIST call
    (`kubectl get <resource> -o json`, no explicit names) and return the
    objects keyed by metadata.name.

    This is the one true batching primitive for "does this desired set of
    names exist" checks: a single LIST is one apiserver round trip no matter
    how many names the caller ultimately needs to check, whereas asking for
    several explicitly-named refs in one kubectl invocation (e.g.
    `kubectl get kind/name kind/name ...`) still costs the apiserver one GET
    per name even though it is one subprocess/timeout -- it only ever looked
    batched from the client side. Callers do the desired-name membership
    check locally against the dict this returns.
    """
    response = kubectl_get_json(kubeconfig, [resource], timeout_seconds, namespace=namespace)
    items = response.get("items")
    if not isinstance(items, list):
        raise ReconcileError(f"kubectl get {resource} returned no usable 'items' list")
    result: Dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("metadata") or {}).get("name")
        if name:
            result[name] = item
    return result


def kubectl_list_names(kubeconfig, resource, timeout_seconds, namespace=None) -> set:
    """List every live object of `resource` in ONE call and return its names.

    Used to prove/disprove an entire desired set of names (e.g. every
    persisted Stage) in a single round trip instead of one existence probe
    per name -- the caller then does a local set comparison.
    """
    return set(kubectl_list_by_name(kubeconfig, resource, timeout_seconds, namespace=namespace))


# ---------------------------------------------------------------------------
# Generic recursive desired-subset comparison
# ---------------------------------------------------------------------------

_LIST_ITEM_KEY_FIELDS = ("name", "key", "type", "containerPort", "address")


def _item_key(item):
    """Best-effort identifying field for matching a list item across desired/actual.

    Returns None when the item has no such field (e.g. a bare string arg), in
    which case callers fall back to trying every actual item.
    """
    if isinstance(item, dict):
        for field_name in _LIST_ITEM_KEY_FIELDS:
            if field_name in item:
                return (field_name, item[field_name])
    return None


def subset_diff(desired, actual, path="$") -> List[str]:
    """Return actionable drift-path strings where `actual` fails to contain `desired`.

    This is a DELIBERATE recursive desired-SUBSET comparison, not an equality
    check, because live Kubernetes objects routinely carry extra
    apiserver/webhook-defaulted fields the desired manifest never specified
    (e.g. an auto-mounted ServiceAccount token volume/volumeMount, default
    port protocol, resource-request normalization):

      * dict: every key present in `desired` must also be present in `actual`
        with a recursively-matching value. Extra keys in `actual` are ignored.
      * list: every item in `desired` must have a matching item SOMEWHERE in
        `actual` (matched by an identifying field such as name/key/type/
        containerPort/address when present, else tried against every actual
        item), itself compared as a subset. Extra items in `actual` are
        ignored (order-independent).
      * scalar: must be equal.

    Every reported difference includes a dotted/indexed `path` so drift is
    actionable (e.g. "spec.containers[0].env: ..." rather than "env drifted").
    """
    errors: List[str] = []
    if isinstance(desired, dict):
        if not isinstance(actual, dict):
            errors.append(f"{path}: expected an object, got {type(actual).__name__}")
            return errors
        for key, desired_value in desired.items():
            if key not in actual:
                errors.append(f"{path}.{key}: missing (want {desired_value!r})")
                continue
            errors.extend(subset_diff(desired_value, actual[key], f"{path}.{key}"))
        return errors

    if isinstance(desired, list):
        if not isinstance(actual, list):
            errors.append(f"{path}: expected a list, got {type(actual).__name__}")
            return errors
        for index, desired_item in enumerate(desired):
            item_path = f"{path}[{index}]"
            key = _item_key(desired_item)
            candidates = actual
            if key is not None:
                candidates = [
                    item for item in actual
                    if isinstance(item, dict) and _item_key(item) == key
                ]
                if not candidates:
                    errors.append(
                        f"{item_path} ({key[0]}={key[1]!r}): no matching item in actual"
                    )
                    continue
            best: Optional[List[str]] = None
            for candidate in candidates:
                candidate_errors = subset_diff(desired_item, candidate, item_path)
                if not candidate_errors:
                    best = []
                    break
                if best is None or len(candidate_errors) < len(best):
                    best = candidate_errors
            errors.extend(best if best is not None else [f"{item_path}: no matching item in actual"])
        return errors

    if desired != actual:
        errors.append(f"{path}: drifted (want {desired!r}, got {actual!r})")
    return errors


# ---------------------------------------------------------------------------
# Inspection + health/drift classification
# ---------------------------------------------------------------------------

def inspect_cluster(
    kubeconfig: str, desired: DesiredState, timeout_seconds: float
) -> Tuple[Dict[str, dict], Dict[str, dict], Dict[str, dict]]:
    """Return (kwok_nodes, agent_pods, real_nodes) keyed by object name."""
    nodes_response = kubectl_get_json(kubeconfig, ["nodes"], timeout_seconds)
    items = nodes_response.get("items")
    if not isinstance(items, list):
        raise ReconcileError("kubectl get nodes returned no usable 'items' list")

    kwok_nodes: Dict[str, dict] = {}
    real_nodes: Dict[str, dict] = {}
    for node in items:
        if not isinstance(node, dict):
            continue
        node_metadata = node.get("metadata")
        name = node_metadata.get("name") if isinstance(node_metadata, dict) else None
        if not name:
            continue
        labels = node_metadata.get("labels") if isinstance(node_metadata, dict) else None
        labels = labels if isinstance(labels, dict) else {}
        if labels.get("type") == KWOK_NODE_TYPE_LABEL_VALUE:
            kwok_nodes[name] = node
        else:
            real_nodes[name] = node

    # Fetch the whole namespace, not only app=mock-cilium-agent. An owned Pod
    # whose app label drifted must still be found and recreated by name; a
    # label-filtered query would misclassify it as missing and race an apply
    # against the still-existing immutable Pod.
    pods_response = kubectl_get_json(
        kubeconfig, ["pods"], timeout_seconds, namespace=desired.namespace,
    )
    pod_items = pods_response.get("items")
    if not isinstance(pod_items, list):
        raise ReconcileError("kubectl get pods returned no usable 'items' list")

    agent_pods: Dict[str, dict] = {}
    for pod in pod_items:
        if not isinstance(pod, dict):
            continue
        pod_metadata = pod.get("metadata")
        name = pod_metadata.get("name") if isinstance(pod_metadata, dict) else None
        labels = pod_metadata.get("labels") if isinstance(pod_metadata, dict) else None
        labels = labels if isinstance(labels, dict) else {}
        if name and (
            name in desired.agent_docs
            or labels.get("app") == AGENT_LABEL_SELECTOR.split("=", 1)[1]
        ):
            agent_pods[name] = pod

    return kwok_nodes, agent_pods, real_nodes


def node_is_healthy(node: dict, desired_doc: dict) -> Tuple[bool, List[str]]:
    """Node healthy = not deleting/NotReady/unschedulable and desired state is a
    subset of live state across ALL behavior-defining fields: labels,
    annotations, providerID, podCIDR/podCIDRs, taints, and desired
    status.addresses/capacity/allocatable (whichever of these the desired
    manifest specifies).
    """
    problems: List[str] = []
    node_metadata = node.get("metadata") or {}
    if node_metadata.get("deletionTimestamp"):
        problems.append("deleting")

    spec = node.get("spec") or {}
    status = node.get("status") or {}

    desired_metadata = desired_doc.get("metadata") or {}
    for field_name in ("labels", "annotations"):
        if field_name in desired_metadata:
            desired_value = desired_metadata[field_name]
            if field_name == "annotations" and isinstance(desired_value, dict):
                desired_value = {
                    key: value
                    for key, value in desired_value.items()
                    if key not in CONTROLLER_OWNED_NODE_ANNOTATIONS
                }
            problems.extend(
                subset_diff(
                    desired_value,
                    node_metadata.get(field_name) or {},
                    f"metadata.{field_name}",
                )
            )

    desired_spec = desired_doc.get("spec") or {}
    for field_name in ("providerID", "podCIDR", "podCIDRs", "taints"):
        if field_name in desired_spec:
            problems.extend(subset_diff(desired_spec[field_name], spec.get(field_name), f"spec.{field_name}"))
    if spec.get("unschedulable"):
        problems.append("unschedulable")

    desired_status = desired_doc.get("status") or {}
    for field_name in ("addresses", "capacity", "allocatable"):
        if field_name in desired_status:
            problems.extend(
                subset_diff(desired_status[field_name], status.get(field_name), f"status.{field_name}")
            )

    conditions = status.get("conditions")
    condition_by_type = {
        c.get("type"): c.get("status") for c in conditions if isinstance(c, dict)
    } if isinstance(conditions, list) else {}
    if condition_by_type.get("Ready") != "True":
        problems.append("NotReady")

    return (not problems, problems)


def agent_is_healthy(
    pod: dict, desired_doc: dict, real_nodes: Dict[str, dict]
) -> Tuple[bool, List[str]]:
    """Agent healthy = Running+Ready, hosted on a healthy real node, and desired
    state is a subset of live state across ALL behavior-defining fields:
    labels, annotations, container command/args/env/resources/ports/
    volumeMounts, affinity, volumes, serviceAccountName, restartPolicy.
    """
    problems: List[str] = []
    pod_metadata = pod.get("metadata") or {}
    if pod_metadata.get("deletionTimestamp"):
        problems.append("deleting")

    status = pod.get("status") or {}
    if status.get("phase") != "Running":
        problems.append(f"phase={status.get('phase')}")
    container_statuses = status.get("containerStatuses")
    container_statuses = container_statuses if isinstance(container_statuses, list) else []
    if not container_statuses or not all(
        isinstance(cs, dict) and cs.get("ready") for cs in container_statuses
    ):
        problems.append("container not Ready")

    desired_metadata = desired_doc.get("metadata") or {}
    for field_name in ("labels", "annotations"):
        if field_name in desired_metadata:
            problems.extend(
                subset_diff(
                    desired_metadata[field_name],
                    pod_metadata.get(field_name) or {},
                    f"metadata.{field_name}",
                )
            )

    spec = pod.get("spec") or {}
    desired_spec = desired_doc.get("spec") or {}

    for field_name in ("serviceAccountName", "restartPolicy"):
        if field_name in desired_spec:
            problems.extend(subset_diff(desired_spec[field_name], spec.get(field_name), f"spec.{field_name}"))
    if "affinity" in desired_spec:
        problems.extend(subset_diff(desired_spec["affinity"], spec.get("affinity") or {}, "spec.affinity"))
    if "volumes" in desired_spec:
        problems.extend(subset_diff(desired_spec["volumes"], spec.get("volumes") or [], "spec.volumes"))

    desired_containers = desired_spec.get("containers")
    desired_containers = desired_containers if isinstance(desired_containers, list) else []
    containers = spec.get("containers")
    containers = containers if isinstance(containers, list) else []
    containers_by_name = {
        container.get("name"): container for container in containers if isinstance(container, dict)
    }
    for index, desired_container in enumerate(desired_containers):
        container_name = desired_container.get("name") if isinstance(desired_container, dict) else None
        actual_container = containers_by_name.get(container_name)
        if actual_container is None:
            problems.append(f"spec.containers[{index}] (name={container_name!r}): missing in live pod")
            continue
        for field_name in ("image", "command", "args", "env", "resources", "ports", "volumeMounts"):
            if field_name in desired_container:
                problems.extend(
                    subset_diff(
                        desired_container[field_name],
                        actual_container.get(field_name),
                        f"spec.containers[{index}].{field_name}",
                    )
                )

    host_node_name = spec.get("nodeName")
    if host_node_name:
        host_node = real_nodes.get(host_node_name)
        if host_node is None:
            problems.append(f"hosted on unknown real node {host_node_name!r}")
        else:
            host_metadata = host_node.get("metadata") or {}
            if host_metadata.get("deletionTimestamp"):
                problems.append(f"hosted on deleting real node {host_node_name!r}")
            else:
                host_status = host_node.get("status") or {}
                host_conditions = host_status.get("conditions")
                host_condition_by_type = {
                    c.get("type"): c.get("status") for c in host_conditions if isinstance(c, dict)
                } if isinstance(host_conditions, list) else {}
                if host_condition_by_type.get("Ready") != "True":
                    problems.append(f"hosted on NotReady real node {host_node_name!r}")

    return (not problems, problems)


# ---------------------------------------------------------------------------
# ClusterMesh consume-secret reconciliation
# ---------------------------------------------------------------------------

def _sanitize_secret_for_copy(secret: dict, target_namespace: str) -> dict:
    """Rebuild a minimal, sanitized Secret doc suitable for re-applying into
    `target_namespace`, matching the STRIP pipeline provision-kwok-layer.sh
    uses when it first copies these secrets (metadata.namespace/resourceVersion/
    uid/creationTimestamp/ownerReferences/managedFields/annotations/status all
    dropped) -- only name/type/data survive.
    """
    metadata = secret.get("metadata") or {}
    return {
        "apiVersion": secret.get("apiVersion", "v1"),
        "kind": "Secret",
        "metadata": {"name": metadata.get("name"), "namespace": target_namespace},
        "type": secret.get("type", "Opaque"),
        "data": secret.get("data") or {},
    }


def _secret_is_drifted(source: dict, target: Optional[dict]) -> bool:
    if target is None:
        return True
    if source.get("type", "Opaque") != target.get("type", "Opaque"):
        return True
    return (source.get("data") or {}) != (target.get("data") or {})


def reconcile_clustermesh_secrets(kubeconfig: str, agent_namespace: str, timeout_seconds: float) -> List[str]:
    """Ensure the four clustermesh consume-path secrets are present and in sync
    in `agent_namespace`, sourced from kube-system.

    Batches the reads: ONE true `kubectl get secrets -o json` LIST in
    kube-system, then ONE more in `agent_namespace` -- two kubectl round
    trips total instead of eight (one get per secret per namespace) -- with
    the four required names selected locally out of each LIST response.
    Returns the sorted list of secret names that were (re)applied because
    they were missing or drifted (data/type) from the kube-system source;
    repairs themselves stay per-object applies. Raises
    UnsafeSourceSecretMissing if any SOURCE secret itself is absent from
    kube-system -- that is unconditionally unsafe (the consume path can
    never legitimately work without it), so it is never silently
    skipped/repaired.
    """
    sources = kubectl_list_by_name(
        kubeconfig, "secrets", timeout_seconds, namespace=CLUSTERMESH_SOURCE_NAMESPACE,
    )
    missing_sources = sorted(
        name for name in CLUSTERMESH_SECRET_NAMES if name not in sources
    )
    if missing_sources:
        raise UnsafeSourceSecretMissing(
            f"clustermesh consume path requires source secret(s) in "
            f"{CLUSTERMESH_SOURCE_NAMESPACE}: {missing_sources}, but "
            f"missing -- refusing to reconcile an unsafe consume-secret configuration"
        )

    targets = kubectl_list_by_name(
        kubeconfig, "secrets", timeout_seconds, namespace=agent_namespace,
    )

    repaired: List[str] = []
    for name in CLUSTERMESH_SECRET_NAMES:
        source = sources[name]
        target = targets.get(name)
        if _secret_is_drifted(source, target):
            kubectl_apply_doc(
                kubeconfig,
                _sanitize_secret_for_copy(source, agent_namespace),
                timeout_seconds,
                namespace=agent_namespace,
            )
            repaired.append(name)
    return sorted(repaired)


# ---------------------------------------------------------------------------
# KWOK support-infra reconciliation (kwok-controller, Stage, APF, RBAC)
# ---------------------------------------------------------------------------

# Kubernetes resource (plural, lowercase) each APF kind LISTs as.
_APF_RESOURCE_BY_KIND = {
    "PriorityLevelConfiguration": "prioritylevelconfigurations",
    "FlowSchema": "flowschemas",
}


def kwok_controller_available(
    kubeconfig: str, deploy_doc: dict, timeout_seconds: float
) -> Tuple[bool, List[str]]:
    metadata = deploy_doc.get("metadata") or {}
    name = metadata.get("name")
    namespace = metadata.get("namespace", "kube-system")
    try:
        live = kubectl_get_json(kubeconfig, ["deployment", name], timeout_seconds, namespace=namespace)
    except ReconcileError as exc:
        return False, [f"kwok-controller Deployment {namespace}/{name} unavailable: {exc}"]
    status = live.get("status") or {}
    desired_replicas = (deploy_doc.get("spec") or {}).get("replicas", 1)
    available = status.get("availableReplicas", 0)
    if available < desired_replicas:
        return False, [
            f"kwok-controller Deployment {namespace}/{name} availableReplicas="
            f"{available} < desired {desired_replicas}"
        ]
    return True, []


def support_infra_is_healthy(
    kubeconfig: str, desired: DesiredState, timeout_seconds: float
) -> Tuple[bool, List[str]]:
    """Verify the persisted KWOK support infra: kwok-controller Deployment
    availability, desired Stage objects, APF PriorityLevelConfiguration/
    FlowSchema, the RBAC Namespace(s), and the agent
    ServiceAccount/ClusterRoleBinding.

    Batches every presence check into as few kubectl round trips as
    possible (one per resource type/namespace, rather than one existence
    probe per object): Stage/APF/Namespace/ServiceAccount/ClusterRoleBinding
    are each proved via a single true `kubectl get <resource> -o json` LIST
    call, with the desired names compared against the LIST result locally --
    never one `get kind/name kind/name ...` per batch of named objects,
    which still costs the apiserver one GET per name even packed into a
    single kubectl subprocess/timeout. This is what previously drove
    ~8-10 serial existence probes per cluster per attempt down to a small,
    object-count-independent number of total calls.

    A missing desired Namespace is recoverable support drift, not a hard
    failure: recording it as a problem here (rather than letting the
    subsequent namespaced ServiceAccount LIST 404 and raise) lets
    reconcile_support_infra re-apply the persisted RBAC manifest -- which
    includes the Namespace doc itself -- and recheck, instead of aborting
    the whole cluster with a NotFound. A genuine failure of the (always
    cluster-scoped, never NotFound-prone) Namespace LIST call itself --
    e.g. an apiserver outage -- still propagates as a ReconcileError so
    reconcile_support_infra fails closed rather than treating it as
    resolvable drift.
    """
    manifests = desired.support_manifests
    assert manifests is not None  # callers only invoke this when support state exists

    problems: List[str] = []

    kwok_deploy = _find_doc(manifests["kwok_controller"], "Deployment")
    if kwok_deploy is None:
        raise ReconcileError("persisted kwok-controller support manifest has no Deployment document")
    _, reasons = kwok_controller_available(kubeconfig, kwok_deploy, timeout_seconds)
    problems.extend(reasons)

    # Stage: ONE list call proves the whole desired set at once.
    stage_names = [
        (doc.get("metadata") or {}).get("name")
        for doc in manifests["stage"] if doc.get("kind") == "Stage"
    ]
    if stage_names:
        live_stage_names = kubectl_list_names(kubeconfig, "stage", timeout_seconds)
        for name in stage_names:
            if name not in live_stage_names:
                problems.append(f"missing Stage {name}")

    # APF (PriorityLevelConfiguration/FlowSchema): both cluster-scoped, so
    # each kind is provable with one true LIST call -- one for
    # PriorityLevelConfigurations, one for FlowSchemas -- with desired names
    # compared locally against each LIST result.
    apf_names_by_kind: Dict[str, List[str]] = {}
    for doc in manifests["apf"]:
        kind = doc.get("kind")
        if kind in _APF_RESOURCE_BY_KIND:
            apf_names_by_kind.setdefault(kind, []).append((doc.get("metadata") or {}).get("name"))
    for kind, resource in _APF_RESOURCE_BY_KIND.items():
        desired_names = apf_names_by_kind.get(kind)
        if not desired_names:
            continue
        live_names = kubectl_list_names(kubeconfig, resource, timeout_seconds)
        for name in desired_names:
            if name not in live_names:
                problems.append(f"missing {kind} {name}")

    # Namespace: cluster-scoped, so provable with one true LIST call, done
    # BEFORE the namespaced ServiceAccount checks below. A missing desired
    # Namespace is recorded as a problem (not raised) and its name is
    # remembered so the ServiceAccount LIST for that namespace can be
    # skipped -- listing ServiceAccounts in a namespace that doesn't exist
    # is itself a kubectl NotFound failure (a raised ReconcileError), which
    # would otherwise turn recoverable "namespace was deleted" drift into an
    # unhandled exception instead of a normal, repairable unhealthy result.
    namespace_names = [
        (doc.get("metadata") or {}).get("name")
        for doc in manifests["rbac"] if doc.get("kind") == "Namespace"
    ]
    missing_namespaces = set()
    if namespace_names:
        live_namespace_names = kubectl_list_names(kubeconfig, "namespaces", timeout_seconds)
        for name in namespace_names:
            if name not in live_namespace_names:
                problems.append(f"missing Namespace {name}")
                missing_namespaces.add(name)

    # RBAC: ServiceAccount is namespaced, ClusterRoleBinding is cluster-scoped
    # -- never combined into one command. Group ServiceAccount refs by their
    # actual target namespace (usually just the agent namespace, but a
    # persisted manifest could in principle name a different one) so each
    # LIST call stays namespace-correct; ClusterRoleBinding gets its own
    # single cluster-scoped LIST call.
    sa_names_by_namespace: Dict[str, List[str]] = {}
    crb_names = []
    for doc in manifests["rbac"]:
        kind = doc.get("kind")
        metadata = doc.get("metadata") or {}
        name = metadata.get("name")
        if kind == "ServiceAccount":
            namespace = metadata.get("namespace", desired.namespace)
            sa_names_by_namespace.setdefault(namespace, []).append(name)
        elif kind == "ClusterRoleBinding":
            crb_names.append(name)

    for namespace in sorted(sa_names_by_namespace):
        if namespace in missing_namespaces:
            # Already recorded as a missing Namespace above; a ServiceAccount
            # LIST against a namespace that doesn't exist would itself raise
            # a NotFound ReconcileError instead of yielding a clean
            # membership check, so skip it here -- reconcile_support_infra
            # will re-apply the persisted RBAC (Namespace+SA+CRB) and recheck.
            continue
        desired_names = sa_names_by_namespace[namespace]
        live_sa_names = kubectl_list_names(kubeconfig, "serviceaccounts", timeout_seconds, namespace=namespace)
        for name in desired_names:
            if name not in live_sa_names:
                problems.append(f"missing ServiceAccount {namespace}/{name}")

    if crb_names:
        live_crb_names = kubectl_list_names(kubeconfig, "clusterrolebindings", timeout_seconds)
        for name in crb_names:
            if name not in live_crb_names:
                problems.append(f"missing ClusterRoleBinding {name}")

    return (not problems, problems)


def apply_support_manifests(kubeconfig: str, desired: DesiredState, timeout_seconds: float) -> None:
    """Re-apply ONLY the exact persisted support manifests -- never redownloaded
    or re-derived. Order follows provision-kwok-layer.sh's own apply order
    (RBAC/APF/Stage before the controller is largely order-independent since
    every doc here is idempotent, but kwok-controller last keeps its rollout
    wait -- performed by the caller's bounded retry loop -- meaningful).
    """
    for key in ("rbac", "apf", "stage", "kwok_controller"):
        for doc in desired.support_manifests[key]:
            kubectl_apply_doc(kubeconfig, doc, timeout_seconds)


def reconcile_support_infra(
    kubeconfig: str,
    desired: DesiredState,
    attempts: int,
    settle_seconds: float,
    request_timeout_seconds: float,
) -> Tuple[List[str], List[str]]:
    """Verify + (if needed) repair the persisted KWOK support infra.

    No-op (returns ([], [])) when desired.support_manifests is None -- the
    persisted state predates support-manifest persistence, so this cluster's
    desired state simply has nothing to check here (back-compat).

    On drift, re-applies the persisted manifests and re-checks on each of the
    bounded `attempts` (with `settle_seconds` between), which doubles as the
    bounded wait for the kwok-controller rollout after a repair. Returns
    (repaired_reasons, errors): repaired_reasons is the sorted set of unhealthy
    reasons observed across attempts (empty if it was already healthy).
    """
    if desired.support_manifests is None:
        return [], []

    repaired_reasons: List[str] = []
    for attempt in range(1, attempts + 1):
        try:
            healthy, problems = support_infra_is_healthy(kubeconfig, desired, request_timeout_seconds)
        except ReconcileError as exc:
            if attempt < attempts:
                time.sleep(settle_seconds)
                continue
            return repaired_reasons, [str(exc)]

        if healthy:
            return repaired_reasons, []

        repaired_reasons = sorted(set(repaired_reasons) | set(problems))
        try:
            apply_support_manifests(kubeconfig, desired, request_timeout_seconds)
        except ReconcileError as exc:
            if attempt < attempts:
                time.sleep(settle_seconds)
                continue
            return repaired_reasons, [str(exc)]

        if attempt < attempts:
            time.sleep(settle_seconds)

    # Bounded repair/rollout-wait budget exhausted -- one last judgment.
    try:
        healthy, problems = support_infra_is_healthy(kubeconfig, desired, request_timeout_seconds)
    except ReconcileError as exc:
        return repaired_reasons, [str(exc)]
    if healthy:
        return repaired_reasons, []
    return (
        repaired_reasons,
        problems or ["kwok support-infra repair attempts exhausted without reaching a healthy state"],
    )


# ---------------------------------------------------------------------------
# Planning + repair
# ---------------------------------------------------------------------------

def plan_repairs(
    desired: DesiredState,
    kwok_nodes: Dict[str, dict],
    agent_pods: Dict[str, dict],
    real_nodes: Dict[str, dict],
) -> ReconcilePlan:
    extra_nodes = sorted(set(kwok_nodes) - set(desired.node_docs))
    extra_agents = sorted(set(agent_pods) - set(desired.agent_docs))

    nodes_to_recreate = []
    for name, doc in desired.node_docs.items():
        node = kwok_nodes.get(name)
        if node is None or not node_is_healthy(node, doc)[0]:
            nodes_to_recreate.append(name)

    agents_to_recreate = set()
    for name, doc in desired.agent_docs.items():
        pod = agent_pods.get(name)
        if pod is None or not agent_is_healthy(pod, doc, real_nodes)[0]:
            agents_to_recreate.add(name)

    # A recreated Node gets a fresh identity (podCIDR/providerID reapplied) --
    # its paired agent MUST be recreated too, even if it currently looks healthy.
    for node_name in nodes_to_recreate:
        agents_to_recreate.add(desired.agent_for_node[node_name])

    return ReconcilePlan(
        nodes_to_recreate=sorted(nodes_to_recreate),
        agents_to_recreate=sorted(agents_to_recreate),
        extra_nodes=extra_nodes,
        extra_agents=extra_agents,
    )


def repair_diagnostics(
    desired: DesiredState,
    plan: ReconcilePlan,
    kwok_nodes: Dict[str, dict],
    agent_pods: Dict[str, dict],
    real_nodes: Dict[str, dict],
) -> dict:
    """Summarize why this plan wants each object recreated.

    Keep the complete counts plus only a few named samples so a large drift
    remains actionable without producing a multi-megabyte summary.
    """
    node_problems = {}
    for name in plan.nodes_to_recreate:
        node = kwok_nodes.get(name)
        node_problems[name] = (
            ["missing"]
            if node is None
            else node_is_healthy(node, desired.node_docs[name])[1]
        )

    agent_problems = {}
    for name in plan.agents_to_recreate:
        pod = agent_pods.get(name)
        problems = (
            ["missing"]
            if pod is None
            else agent_is_healthy(pod, desired.agent_docs[name], real_nodes)[1]
        )
        if not problems:
            problems = ["paired-with-node-repair"]
        agent_problems[name] = problems

    def _summarize(problem_map):
        counts = {}
        for problems in problem_map.values():
            for problem in problems:
                counts[problem] = counts.get(problem, 0) + 1
        return {
            "problem_counts": [
                {"problem": problem, "count": count}
                for problem, count in sorted(
                    counts.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
            "samples": {
                name: problem_map[name]
                for name in sorted(problem_map)[:3]
            },
        }

    return {
        "nodes": _summarize(node_problems),
        "agents": _summarize(agent_problems),
    }


def mass_present_node_drift(
    desired: DesiredState,
    plan: ReconcilePlan,
    kwok_nodes: Dict[str, dict],
) -> Tuple[bool, int, int]:
    """Detect a systemic transition that is unsafe to repair destructively.

    Missing Nodes can be recreated safely from persisted desired state. Present
    Nodes that simultaneously look unhealthy are different: deleting a large
    fraction can turn a transient controller/API-server transition into a full
    mock-layer outage. Refuse that bulk delete and let bounded retries observe
    whether the shared condition clears. This fuse is deliberately Node-only:
    Pods are replaceable scheduling units and batched agent-only repair does not
    destroy the synthetic Node identities/CiliumNode state being measured.
    """
    present_repairs = sum(
        1 for name in plan.nodes_to_recreate if name in kwok_nodes
    )
    threshold = max(10, (len(desired.node_docs) + 3) // 4)
    return present_repairs >= threshold, present_repairs, threshold


def apply_repairs(kubeconfig: str, desired: DesiredState, plan: ReconcilePlan, timeout_seconds: float) -> None:
    # Delete first (Node identity fields like podCIDR/providerID are immutable,
    # so a drifted/unhealthy object must be deleted before it can be reapplied).
    kubectl_delete_many(
        kubeconfig,
        "pod",
        plan.agents_to_recreate,
        timeout_seconds,
        namespace=desired.namespace,
    )
    kubectl_delete_many(
        kubeconfig,
        "node",
        plan.nodes_to_recreate,
        timeout_seconds,
    )
    # Recreate nodes before their agents (an agent's K8S_NODE_NAME identity
    # references its node), matching provision-kwok-layer.sh's apply order.
    kubectl_apply_docs(
        kubeconfig,
        (desired.node_docs[name] for name in plan.nodes_to_recreate),
        timeout_seconds,
    )
    kubectl_apply_docs(
        kubeconfig,
        (desired.agent_docs[name] for name in plan.agents_to_recreate),
        timeout_seconds,
        namespace=desired.namespace,
    )


def _extra_object_errors(plan: ReconcilePlan) -> List[str]:
    errors = []
    if plan.extra_nodes:
        errors.append(
            f"unsafe drift: {len(plan.extra_nodes)} extra KWOK node(s) outside the desired "
            f"manifest (refusing to delete): {plan.extra_nodes}"
        )
    if plan.extra_agents:
        errors.append(
            f"unsafe drift: {len(plan.extra_agents)} extra mock-agent pod(s) outside the "
            f"desired manifest (refusing to delete): {plan.extra_agents}"
        )
    return errors


def validate_converged(
    desired: DesiredState,
    kwok_nodes: Dict[str, dict],
    agent_pods: Dict[str, dict],
    real_nodes: Dict[str, dict],
) -> List[str]:
    """Final gate: exact names/counts, every object healthy, unique 1:1 coverage, no extras."""
    errors: List[str] = []
    desired_node_names = set(desired.node_docs)
    desired_agent_names = set(desired.agent_docs)
    actual_node_names = set(kwok_nodes)
    actual_agent_names = set(agent_pods)

    missing_nodes = sorted(desired_node_names - actual_node_names)
    if missing_nodes:
        errors.append(f"missing KWOK node(s): {missing_nodes}")
    extra_nodes = sorted(actual_node_names - desired_node_names)
    if extra_nodes:
        errors.append(f"unsafe drift: extra KWOK node(s) outside desired manifest: {extra_nodes}")

    missing_agents = sorted(desired_agent_names - actual_agent_names)
    if missing_agents:
        errors.append(f"missing mock-agent pod(s): {missing_agents}")
    extra_agents = sorted(actual_agent_names - desired_agent_names)
    if extra_agents:
        errors.append(f"unsafe drift: extra mock-agent pod(s) outside desired manifest: {extra_agents}")

    for name, doc in desired.node_docs.items():
        node = kwok_nodes.get(name)
        if node is None:
            continue
        healthy, reasons = node_is_healthy(node, doc)
        if not healthy:
            errors.append(f"node {name} unhealthy: {', '.join(reasons)}")

    served_by: Dict[str, List[str]] = {}
    for name, doc in desired.agent_docs.items():
        pod = agent_pods.get(name)
        if pod is None:
            continue
        healthy, reasons = agent_is_healthy(pod, doc, real_nodes)
        if not healthy:
            errors.append(f"agent {name} unhealthy: {', '.join(reasons)}")
        pod_metadata = pod.get("metadata") or {}
        labels = pod_metadata.get("labels") or {}
        served = labels.get(SERVES_NODE_LABEL)
        if served:
            served_by.setdefault(served, []).append(name)

    served_nodes = set(served_by)
    if served_nodes != desired_node_names:
        errors.append(
            "serves-node coverage is not a unique one-to-one mapping onto the desired nodes"
        )
    for served, agents in served_by.items():
        if len(agents) > 1:
            errors.append(f"duplicate serves-node coverage for {served}: agents {sorted(agents)}")

    return errors


# ---------------------------------------------------------------------------
# Per-cluster orchestration
# ---------------------------------------------------------------------------

def reconcile_cluster(
    role: str,
    kubeconfig: str,
    state_root: str,
    expected_count: Optional[int],
    attempts: int,
    settle_seconds: float,
    request_timeout_seconds: float,
    run_id: Optional[str] = None,
) -> dict:
    result = {
        "role": role,
        "status": "failed",
        "attempts_used": 0,
        "recreated_nodes": [],
        "recreated_agents": [],
        "repaired_secrets": [],
        "repaired_support": [],
        "repair_diagnostics": {},
        "errors": [],
    }

    state_dir = os.path.join(state_root, role)
    try:
        desired = load_desired_state(state_dir)
    except ReconcileError as exc:
        result["errors"] = [str(exc)]
        _progress(role, "desired-state", f"FAILED to load: {exc}")
        return result

    _progress(
        role, "desired-state",
        f"loaded {len(desired.node_docs)} node(s)/{len(desired.agent_docs)} agent(s); "
        f"support_manifests={'present' if desired.support_manifests is not None else 'absent'}; "
        f"consume_clustermesh={bool(desired.metadata.get('consume_clustermesh'))}",
    )

    # A persisted desired state must belong to the run currently reconciling
    # against it -- without this, a role-scoped-only state dir left over from a
    # DIFFERENT run (different NODE_COUNT/ACR/agent image/topology) could be
    # silently reused, "repairing" a cluster back to stale desired state.
    if run_id is not None:
        persisted_run_id = desired.metadata.get("run_id")
        if persisted_run_id != run_id:
            result["errors"] = [
                f"stale desired state: persisted metadata run_id {persisted_run_id!r} "
                f"does not match the expected run_id {run_id!r} -- refusing to "
                f"reconcile against a different run's desired state"
            ]
            _progress(role, "desired-state", f"FAILED: {result['errors'][0]}")
            return result

    if expected_count is not None and len(desired.node_docs) != expected_count:
        result["errors"] = [
            f"persisted desired state has {len(desired.node_docs)} node(s), "
            f"expected {expected_count}"
        ]
        _progress(role, "desired-state", f"FAILED: {result['errors'][0]}")
        return result

    # KWOK support infra (kwok-controller, Stage, APF, RBAC) is the first
    # precondition. The persisted RBAC manifest also owns the mock agent
    # Namespace, so it must be restored before consume secrets can be copied
    # into that namespace.
    _progress(role, "support", "checking support-infra (kwok-controller/stage/apf/rbac)")
    repaired_support, support_errors = reconcile_support_infra(
        kubeconfig, desired, attempts, settle_seconds, request_timeout_seconds,
    )
    result["repaired_support"] = repaired_support
    if support_errors:
        result["errors"] = support_errors
        _progress(role, "support", f"FAILED: {'; '.join(support_errors)}")
        return result
    _progress(
        role, "support",
        f"healthy (repaired {len(repaired_support)} reason(s))" if repaired_support
        else "healthy (no repair needed)",
    )

    # ClusterMesh consume secrets: an independent precondition, reconciled once
    # (with its own bounded retries) after support/RBAC has ensured the target
    # namespace exists. A missing SOURCE secret is unconditionally unsafe and
    # fails the cluster immediately -- no amount of node/agent repair fixes a
    # broken consume path.
    if desired.metadata.get("consume_clustermesh"):
        _progress(role, "secrets", "checking clustermesh consume secrets")
        secrets_errors: List[str] = []
        for attempt in range(1, attempts + 1):
            try:
                result["repaired_secrets"] = reconcile_clustermesh_secrets(
                    kubeconfig, desired.namespace, request_timeout_seconds
                )
                secrets_errors = []
                break
            except UnsafeSourceSecretMissing as exc:
                result["errors"] = [str(exc)]
                _progress(role, "secrets", f"FAILED (unsafe): {exc}")
                return result
            except ReconcileError as exc:
                secrets_errors = [str(exc)]
                if attempt < attempts:
                    time.sleep(settle_seconds)
        if secrets_errors:
            result["errors"] = secrets_errors
            _progress(role, "secrets", f"FAILED: {'; '.join(secrets_errors)}")
            return result
        _progress(
            role, "secrets",
            f"in sync (repaired {len(result['repaired_secrets'])} of "
            f"{len(CLUSTERMESH_SECRET_NAMES)} names)",
        )

    recreated_nodes: set = set()
    recreated_agents: set = set()
    errors: List[str] = []
    converged = False
    attempt = 0

    for attempt in range(1, attempts + 1):
        try:
            kwok_nodes, agent_pods, real_nodes = inspect_cluster(
                kubeconfig, desired, request_timeout_seconds
            )
        except ReconcileError as exc:
            errors = [str(exc)]
            _progress(role, "inventory", f"attempt {attempt}/{attempts}: FAILED: {exc}")
            if attempt < attempts:
                time.sleep(settle_seconds)
                continue
            break

        _progress(
            role, "inventory",
            f"attempt {attempt}/{attempts}: live nodes={len(kwok_nodes)} "
            f"agents={len(agent_pods)} real_nodes={len(real_nodes)}",
        )

        plan = plan_repairs(desired, kwok_nodes, agent_pods, real_nodes)
        diagnostics = repair_diagnostics(
            desired, plan, kwok_nodes, agent_pods, real_nodes,
        )
        if plan.nodes_to_recreate or plan.agents_to_recreate:
            result["repair_diagnostics"] = diagnostics
        _progress(
            role, "plan",
            f"attempt {attempt}/{attempts}: recreate_nodes={len(plan.nodes_to_recreate)} "
            f"recreate_agents={len(plan.agents_to_recreate)} "
            f"extra_nodes={len(plan.extra_nodes)} extra_agents={len(plan.extra_agents)}",
        )
        if plan.nodes_to_recreate or plan.agents_to_recreate:
            _progress(
                role,
                "diagnostics",
                f"attempt {attempt}/{attempts}: "
                f"node_problems={diagnostics['nodes']['problem_counts'][:3]} "
                f"agent_problems={diagnostics['agents']['problem_counts'][:3]}",
            )

        if plan.extra_nodes or plan.extra_agents:
            errors = _extra_object_errors(plan)
            _progress(role, "convergence", f"FAILED: unsafe drift: {'; '.join(errors)}")
            break

        mass_drift, present_repairs, mass_drift_threshold = (
            mass_present_node_drift(desired, plan, kwok_nodes)
        )
        if mass_drift:
            errors = [
                "unsafe systemic mock-node drift: "
                f"{present_repairs}/{len(desired.node_docs)} present KWOK Nodes "
                f"require recreation (safety threshold {mass_drift_threshold}); "
                "refusing destructive bulk deletion"
            ]
            _progress(
                role,
                "mass-drift",
                f"attempt {attempt}/{attempts}: {errors[0]}",
            )
            if attempt < attempts:
                time.sleep(settle_seconds)
                continue
            break

        if not plan.nodes_to_recreate and not plan.agents_to_recreate:
            errors = validate_converged(desired, kwok_nodes, agent_pods, real_nodes)
            converged = not errors
            _progress(
                role, "convergence",
                "converged" if converged else f"FAILED validation: {'; '.join(errors)}",
            )
            break

        try:
            apply_repairs(kubeconfig, desired, plan, request_timeout_seconds)
        except ReconcileError as exc:
            errors = [str(exc)]
            _progress(role, "plan", f"attempt {attempt}/{attempts}: repair apply FAILED: {exc}")
            if attempt < attempts:
                time.sleep(settle_seconds)
                continue
            break

        recreated_nodes.update(plan.nodes_to_recreate)
        recreated_agents.update(plan.agents_to_recreate)
        time.sleep(settle_seconds)
    else:
        # Attempts exhausted without an early "nothing left to repair" break --
        # give the last repair one more settle window, then judge convergence.
        try:
            kwok_nodes, agent_pods, real_nodes = inspect_cluster(
                kubeconfig, desired, request_timeout_seconds
            )
            errors = validate_converged(desired, kwok_nodes, agent_pods, real_nodes)
            converged = not errors
            if not converged and not errors:
                errors = ["repair attempts exhausted without reaching a converged state"]
        except ReconcileError as exc:
            errors = [str(exc)]
        _progress(
            role, "convergence",
            "converged (final check)" if converged else f"FAILED: {'; '.join(errors)}",
        )

    result["attempts_used"] = attempt
    result["recreated_nodes"] = sorted(recreated_nodes)
    result["recreated_agents"] = sorted(recreated_agents)
    result["errors"] = errors
    result["status"] = "ok" if converged else "failed"
    _progress(
        role, "done",
        f"status={result['status']} attempts_used={attempt} "
        f"recreated_nodes={len(result['recreated_nodes'])} "
        f"recreated_agents={len(result['recreated_agents'])}",
    )
    return result



def resolve_kubeconfig(cluster: dict) -> str:
    """Explicit 'kubeconfig' field wins; else derive the deploy-mock-layer.yml default."""
    kubeconfig = cluster.get("kubeconfig")
    if kubeconfig:
        return str(kubeconfig)
    role = cluster["role"]
    return os.path.join(os.path.expanduser("~"), ".kube", f"{role}.config")


def reconcile_all(
    clusters: List[dict],
    state_root: str,
    expected_count: Optional[int],
    max_concurrent: int,
    attempts: int,
    settle_seconds: float,
    request_timeout_seconds: float,
    run_id: Optional[str] = None,
    on_result=None,
) -> List[dict]:
    """Reconcile every cluster (bounded concurrency), returning all results.

    `on_result`, if given, is called as `on_result(result, results_so_far,
    pending_roles)` synchronously in THIS (driving) thread immediately after
    each cluster's reconcile_cluster() call returns -- i.e. serialized by
    `as_completed`'s single-threaded iteration, never called concurrently --
    so a caller (see main()'s incremental --summary-file write) can persist
    partial progress without its own locking. This is what lets a killed
    outer-timeout process still leave a JSON summary behind for every
    cluster that had already finished, rather than only "nothing was ever
    written" -- see write_summary()/main().
    """
    results: List[dict] = []
    all_roles = [cluster["role"] for cluster in clusters]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {}
        for cluster in clusters:
            role = cluster["role"]
            kubeconfig = resolve_kubeconfig(cluster)
            future = executor.submit(
                reconcile_cluster,
                role,
                kubeconfig,
                state_root,
                expected_count,
                attempts,
                settle_seconds,
                request_timeout_seconds,
                run_id,
            )
            futures[future] = role
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            if on_result is not None:
                done_roles = {r["role"] for r in results}
                pending_roles = sorted(role for role in all_roles if role not in done_roles)
                on_result(result, list(results), pending_roles)
    return results



def write_summary(path: str, summary: dict) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--clusters", required=True,
        help="Path to a JSON array of cluster objects, each with at least a 'role' "
             "field (e.g. $HOME/.kube/clustermesh-clusters.json). An optional "
             "'kubeconfig' field overrides the default $HOME/.kube/<role>.config path.",
    )
    parser.add_argument(
        "--state-root", required=True,
        help="Base dir containing <state-root>/<role>/{nodes.yaml,agents.yaml,"
             "metadata.json} as persisted by provision-kwok-layer.sh (MOCK_STATE_DIR).",
    )
    parser.add_argument(
        "--expected-mock-count", type=int, default=None,
        help="If set, fail a cluster whose persisted desired state doesn't have "
             "exactly this many nodes (catches stale state from a prior NODE_COUNT).",
    )
    parser.add_argument(
        "--run-id", default=None,
        help="If set, fail a cluster whose persisted desired-state metadata "
             "'run_id' doesn't match this value (catches stale role-only state "
             "left over from a DIFFERENT run being reused by this one).",
    )
    parser.add_argument("--summary-file", required=True, help="Output path for the JSON summary.")
    parser.add_argument(
        "--max-concurrent", type=int, default=8,
        help="Maximum number of clusters reconciled in parallel.",
    )
    parser.add_argument(
        "--attempts", type=int, default=5,
        help="Bounded repair attempts per cluster before giving up.",
    )
    parser.add_argument(
        "--settle-seconds", type=float, default=15.0,
        help="Sleep between repair attempts to let KWOK/kubelet-equivalent state settle.",
    )
    parser.add_argument(
        "--request-timeout-seconds", type=float, default=30.0,
        help="Bounded timeout for each kubectl invocation.",
    )
    return parser.parse_args(argv)


def _build_summary(args, results: List[dict], pending_roles: Optional[List[str]] = None) -> dict:
    """Build the JSON summary dict written to --summary-file.

    `pending_roles` is the set of cluster roles not yet reconciled at the
    time of writing -- non-empty for an INCREMENTAL write emitted right
    after each cluster completes (see main()'s on_result callback below),
    empty for the final write once every cluster has a result. "partial":
    true marks an incremental write so a reader (a human scanning the ADO
    log, or a future automated consumer) can always tell a still-in-progress
    summary apart from a genuinely complete run -- the file on disk always
    reflects reality as of its last successful atomic write, so even a
    process killed by an outer `timeout` mid-run leaves an accurate,
    non-misleading summary behind for whichever clusters had already
    finished, instead of either a stale/absent file or one that silently
    looks "done".
    """
    pending_roles = sorted(pending_roles or [])
    failed = sorted(r["role"] for r in results if r["status"] != "ok")
    return {
        "schema_version": 1,
        "success": not failed and not pending_roles,
        "partial": bool(pending_roles),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "state_root": args.state_root,
        "run_id": args.run_id,
        "expected_mock_count": args.expected_mock_count,
        "total_clusters": len(results) + len(pending_roles),
        "healthy_count": len(results) - len(failed),
        "failed_count": len(failed),
        "failed_roles": failed,
        "pending_roles": pending_roles,
        "results": sorted(results, key=lambda r: r["role"]),
    }


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        with open(args.clusters, "r", encoding="utf-8") as handle:
            clusters = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"mock-layer-reconcile: failed to read {args.clusters}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(clusters, list) or not clusters:
        print(
            f"mock-layer-reconcile: {args.clusters} must be a non-empty JSON array",
            file=sys.stderr,
        )
        return 1
    for index, cluster in enumerate(clusters):
        if not isinstance(cluster, dict) or not cluster.get("role"):
            print(f"mock-layer-reconcile: clusters[{index}] missing 'role'", file=sys.stderr)
            return 1

    if args.max_concurrent < 1:
        print("mock-layer-reconcile: --max-concurrent must be >= 1", file=sys.stderr)
        return 1
    if args.attempts < 1:
        print("mock-layer-reconcile: --attempts must be >= 1", file=sys.stderr)
        return 1

    def _write_incremental_summary(_result, results_so_far, pending_roles) -> None:
        write_summary(args.summary_file, _build_summary(args, results_so_far, pending_roles))

    results = reconcile_all(
        clusters,
        state_root=args.state_root,
        expected_count=args.expected_mock_count,
        max_concurrent=args.max_concurrent,
        attempts=args.attempts,
        settle_seconds=args.settle_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
        run_id=args.run_id,
        on_result=_write_incremental_summary,
    )

    summary = _build_summary(args, results, pending_roles=[])
    write_summary(args.summary_file, summary)

    failed = summary["failed_roles"]
    print(
        f"mock-layer-reconcile: {summary['healthy_count']}/{summary['total_clusters']} "
        f"cluster(s) healthy" + (f"; failed: {failed}" if failed else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
