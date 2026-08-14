#!/usr/bin/env python3
"""Bounded, best-effort cleanup of a scenario's RECOVERABLE Kubernetes residue.

`scenario-health-gate.sh` (config/scenario-health-gate.sh) is PROOF-ONLY: it
observes whether a scenario's namespaces/CRs/monitoring objects are gone and
fails the build if they aren't, but it never deletes anything -- it is (and
remains) the final authority on whether the shared environment is healthy
enough for the next scenario. This module is the ACTIVE repair pass that runs
*before* that gate: if a scenario's own stimulus (or an aborted CL2 run) left
behind Kubernetes objects the gate would otherwise flag as stale, this module
removes them so the next scenario starts clean, without ever second-guessing
the gate's final verdict.

It deliberately touches an exact, narrow allowlist -- the same allowlist the
health gate already treats as "this scenario's own stale residue" -- and
NOTHING else:
  * Namespaces equal to, or hyphen-prefixed by, the CURRENT scenario's own
    namespace prefix (see SCENARIO_NAMESPACE_PREFIXES). A different
    scenario's clustermesh-* namespaces are never touched, even in the same
    run.
  * The two ACNS cluster-scoped CRs (ContainerNetworkLog/clustermesh-scale-acns,
    ContainerNetworkMetric/container-network-metric) and the acns-telemetry
    namespace.
  * Namespaced objects in "monitoring" (discovered across monitoring.coreos.com
    plus core/RBAC resource kinds) whose name starts with one of the scenario-
    owned prefixes the health gate already recognizes (clustermesh-apiserver,
    hubble-metrics, coredns, kvstoremesh-standalone, mock-cilium-agent,
    apiserver-backend-exporter) -- EXCEPT an explicit protected-baseline
    denylist (prometheus-operator, kube-state-metrics, ama-metrics*,
    controlplane-apiserver*, managed-prometheus, ...) that is never deleted
    even if a future allowlist prefix were to accidentally overlap it.
  * ClusterRoles/ClusterRoleBindings named apiserver-backend-exporter*.

Anything outside this allowlist is left strictly alone: an object this module
cannot positively identify as scenario-owned residue is "unsafe drift" that
this pass does not touch (unlike, say, mock_layer_reconcile.py's node/agent
repair, there is no legitimate "recreate" action here -- only "delete
this-and-only-this exact set, and prove it's gone").

Exit code is 0 iff every cluster converges (the allowlisted targets it found
at the start are confirmed absent by the end of the bounded attempt budget)
or was already a healthy no-op; 1 otherwise. A structured, schema-versioned
JSON summary (per-cluster deleted/remaining/errors) is always written
atomically to --summary-file, and a failure here NEVER fabricates success --
an API failure counts as "we don't know", never as "zero remaining".
"""

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple


# Exact scenario -> namespace-prefix allowlist. A scenario name outside this
# map has no known namespace-owned residue and is refused (fail cleanly)
# rather than silently treated as "nothing to clean up".
SCENARIO_NAMESPACE_PREFIXES = {
    "propagation-probe": "clustermesh-probe",
    "event-throughput": "clustermesh-et",
    "pod-churn-combined": "clustermesh-pcc",
    "apiserver-failure": "clustermesh-apf",
    "policy-scale": "clustermesh-pscale",
    "isolation": "clustermesh-iso",
    "node-churn-combined": "clustermesh-ncc",
    "node-churn-scale": "clustermesh-ncs",
    "node-churn-replace": "clustermesh-ncr",
    "upper-bound": "clustermesh-ub",
}

# The two exact ACNS cluster-scoped CRs collect-acns-telemetry.sh normally
# deletes itself at the end of a successful run (see
# scenarios/perf-eval/clustermesh-scale/telemetry/collect-acns-telemetry.sh).
# This pass repeats that exact deletion as a bounded fallback for the case
# where the scenario aborted before that script ran to completion.
ACNS_CLUSTER_SCOPED_RESOURCES = (
    ("containernetworklog", "ContainerNetworkLog", "clustermesh-scale-acns"),
    ("containernetworkmetric", "ContainerNetworkMetric", "container-network-metric"),
)
ACNS_NAMESPACE = "acns-telemetry"

MONITORING_NAMESPACE = "monitoring"

# Core/RBAC resource kinds always checked in "monitoring", mirrored verbatim
# from scenario-health-gate.sh's baseline resource_arg so both tools agree on
# exactly what "scenario-owned monitoring residue" means.
MONITORING_BASELINE_RESOURCE_TYPES = (
    "all",
    "configmaps",
    "secrets",
    "serviceaccounts",
    "persistentvolumeclaims",
    "roles.rbac.authorization.k8s.io",
    "rolebindings.rbac.authorization.k8s.io",
)

# Scenario-owned name prefixes in "monitoring" -- identical to the allowlist
# scenario-health-gate.sh already uses to flag stale monitoring residue.
MONITORING_ALLOWLIST_PREFIXES = (
    "clustermesh-apiserver",
    "hubble-metrics",
    "coredns",
    "kvstoremesh-standalone",
    "mock-cilium-agent",
    "apiserver-backend-exporter",
)

# Explicit, never-touch denylist. Defense in depth: even if a future
# allowlist prefix were ever widened to accidentally overlap one of these,
# this list wins and the object is left alone.
MONITORING_PROTECTED_PREFIXES = (
    "prometheus-operator",
    "kube-state-metrics",
    "ama-metrics",
    "controlplane-apiserver",
    "managed-prometheus",
)

EXPORTER_RBAC_PREFIX = "apiserver-backend-exporter"

_ABSENT_RESOURCE_RE = re.compile(
    r"(the server (could not find|doesn.t have) (the requested resource|a resource type)"
    r"|not found)",
    re.IGNORECASE,
)


class ReconcileError(Exception):
    """An expected, per-cluster cleanup failure (bad state, kubectl error, ...).

    Deliberately distinct from unexpected exceptions (KeyError, TypeError, ...)
    that would indicate a bug in this tool -- those are allowed to propagate
    rather than being swallowed, per the "no broad exception swallowing"
    requirement.
    """


@dataclass(frozen=True)
class TargetRef:
    """One allowlisted object this pass may delete.

    `resource` is the exact string passed to `kubectl delete`/`kubectl get`
    (lowercase kind or plural resource name); `kind` is the display Kind used
    only for the human-/summary-facing identifier.
    """

    resource: str
    kind: str
    name: str
    namespace: Optional[str] = None

    def identifier(self) -> str:
        if self.namespace:
            return f"{self.namespace}/{self.kind}/{self.name}"
        return f"{self.kind}/{self.name}"


# ---------------------------------------------------------------------------
# kubectl plumbing
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


def _is_absent_resource_error(exc: ReconcileError) -> bool:
    """True if `exc` means "this resource type/object doesn't exist here" --

    i.e. zero targets, NOT an API failure. Covers both an uninstalled CRD
    (e.g. ACNS not configured on this cluster) and a missing "monitoring"
    namespace itself.
    """
    return bool(_ABSENT_RESOURCE_RE.search(str(exc)))


def kubectl_get_json(kubeconfig, resource_args, timeout_seconds, namespace=None) -> dict:
    cmd = _base_cmd(kubeconfig, timeout_seconds, namespace) + ["get", *resource_args, "-o", "json"]
    stdout = _run_kubectl(cmd, timeout_seconds)
    try:
        return json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ReconcileError(
            f"kubectl returned invalid JSON for: {' '.join(cmd)}: {exc}"
        ) from exc


def kubectl_get_optional_json(kubeconfig, resource_args, timeout_seconds, namespace=None) -> Optional[dict]:
    """Like kubectl_get_json, but returns None (instead of raising) when the
    resource type/namespace is simply absent -- i.e. zero targets."""
    try:
        return kubectl_get_json(kubeconfig, resource_args, timeout_seconds, namespace=namespace)
    except ReconcileError as exc:
        if _is_absent_resource_error(exc):
            return None
        raise


def kubectl_object_exists(kubeconfig, kind, name, timeout_seconds, namespace=None) -> bool:
    cmd = _base_cmd(kubeconfig, timeout_seconds, namespace) + ["get", kind, name]
    try:
        _run_kubectl(cmd, timeout_seconds)
        return True
    except ReconcileError as exc:
        if _is_absent_resource_error(exc):
            return False
        raise


def kubectl_delete(kubeconfig, kind, name, timeout_seconds, namespace=None, wait=True) -> None:
    cmd = _base_cmd(kubeconfig, timeout_seconds, namespace) + [
        "delete", kind, name, "--ignore-not-found=true",
        f"--timeout={timeout_seconds}s",
    ]
    if not wait:
        cmd += ["--wait=false"]
    _run_kubectl(cmd, timeout_seconds + 5)


def discover_monitoring_resource_types(kubeconfig, timeout_seconds) -> List[str]:
    cmd = _base_cmd(kubeconfig, timeout_seconds) + [
        "api-resources", "--api-group=monitoring.coreos.com",
        "--verbs=list", "--namespaced=true", "-o", "name",
    ]
    stdout = _run_kubectl(cmd, timeout_seconds)
    return [line.strip() for line in stdout.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Target discovery -- each function raises ReconcileError on a genuine API
# failure and returns an empty/False result when the object/type is simply
# absent (i.e. zero targets, NOT an error).
# ---------------------------------------------------------------------------

def list_scenario_namespaces(kubeconfig, namespace_prefix, timeout_seconds) -> List[str]:
    payload = kubectl_get_json(kubeconfig, ["namespaces"], timeout_seconds)
    items = payload.get("items")
    if not isinstance(items, list):
        raise ReconcileError("namespace list response was not a Kubernetes List")
    names = []
    for item in items:
        name = (item.get("metadata") or {}).get("name")
        if not isinstance(name, str) or not name:
            continue
        if name == namespace_prefix or name.startswith(namespace_prefix + "-"):
            names.append(name)
    return sorted(names)


def list_monitoring_targets(kubeconfig, timeout_seconds) -> List[Tuple[str, str]]:
    try:
        discovered_types = discover_monitoring_resource_types(kubeconfig, timeout_seconds)
    except ReconcileError as exc:
        if _is_absent_resource_error(exc):
            discovered_types = []
        else:
            raise
    resource_arg = ",".join(MONITORING_BASELINE_RESOURCE_TYPES + tuple(discovered_types))
    payload = kubectl_get_optional_json(
        kubeconfig, [resource_arg], timeout_seconds, namespace=MONITORING_NAMESPACE
    )
    if payload is None:
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        raise ReconcileError("monitoring resource response was not a Kubernetes List")
    targets = []
    for item in items:
        kind = item.get("kind")
        name = (item.get("metadata") or {}).get("name")
        if not isinstance(kind, str) or not isinstance(name, str) or not name:
            continue
        if any(name.startswith(prefix) for prefix in MONITORING_PROTECTED_PREFIXES):
            continue
        if any(name.startswith(prefix) for prefix in MONITORING_ALLOWLIST_PREFIXES):
            targets.append((kind, name))
    return sorted(targets)


def list_exporter_rbac_targets(kubeconfig, timeout_seconds) -> List[Tuple[str, str]]:
    payload = kubectl_get_optional_json(
        kubeconfig,
        ["clusterroles.rbac.authorization.k8s.io,clusterrolebindings.rbac.authorization.k8s.io"],
        timeout_seconds,
    )
    if payload is None:
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        raise ReconcileError("exporter RBAC response was not a Kubernetes List")
    targets = []
    for item in items:
        kind = item.get("kind")
        name = (item.get("metadata") or {}).get("name")
        if isinstance(kind, str) and isinstance(name, str) and name.startswith(EXPORTER_RBAC_PREFIX):
            targets.append((kind, name))
    return sorted(targets)


def gather_targets(kubeconfig, namespace_prefix, timeout_seconds) -> List[TargetRef]:
    targets: List[TargetRef] = []

    for name in list_scenario_namespaces(kubeconfig, namespace_prefix, timeout_seconds):
        targets.append(TargetRef("namespace", "Namespace", name))

    if kubectl_object_exists(kubeconfig, "namespace", ACNS_NAMESPACE, timeout_seconds):
        targets.append(TargetRef("namespace", "Namespace", ACNS_NAMESPACE))

    for resource, kind, name in ACNS_CLUSTER_SCOPED_RESOURCES:
        if kubectl_object_exists(kubeconfig, resource, name, timeout_seconds):
            targets.append(TargetRef(resource, kind, name))

    for kind, name in list_monitoring_targets(kubeconfig, timeout_seconds):
        targets.append(TargetRef(kind.lower(), kind, name, namespace=MONITORING_NAMESPACE))

    for kind, name in list_exporter_rbac_targets(kubeconfig, timeout_seconds):
        targets.append(TargetRef(kind.lower(), kind, name))

    return targets


def delete_targets(kubeconfig, targets: List[TargetRef], timeout_seconds) -> None:
    """Best-effort delete of every target; a per-item failure does not stop
    the others in this same attempt from being tried. Namespaces are deleted
    with --wait=false (they can take a long time to finalize); their absence
    is instead confirmed by re-listing on the next attempt/final check.
    """
    errors: List[str] = []
    for target in targets:
        wait = target.kind != "Namespace"
        try:
            kubectl_delete(
                kubeconfig, target.resource, target.name, timeout_seconds,
                namespace=target.namespace, wait=wait,
            )
        except ReconcileError as exc:
            errors.append(str(exc))
    if errors:
        raise ReconcileError("; ".join(errors))


# ---------------------------------------------------------------------------
# Per-cluster / all-clusters reconciliation
# ---------------------------------------------------------------------------

def reconcile_cluster(
    role: str,
    kubeconfig: str,
    namespace_prefix: str,
    attempts: int,
    settle_seconds: float,
    request_timeout_seconds: float,
) -> dict:
    result = {
        "role": role,
        "status": "failed",
        "attempts_used": 0,
        "no_op": False,
        "deleted": [],
        "remaining": None,
        "errors": [],
    }

    initial_ids: Optional[set] = None
    remaining_ids: Optional[set] = None
    errors: List[str] = []
    converged = False
    attempt = 0

    for attempt in range(1, attempts + 1):
        try:
            targets = gather_targets(kubeconfig, namespace_prefix, request_timeout_seconds)
        except ReconcileError as exc:
            errors = [str(exc)]
            if attempt < attempts:
                time.sleep(settle_seconds)
                continue
            break

        current_ids = {target.identifier() for target in targets}
        if initial_ids is None:
            initial_ids = set(current_ids)

        if not current_ids:
            errors = []
            converged = True
            remaining_ids = set()
            break

        try:
            delete_targets(kubeconfig, targets, request_timeout_seconds)
            errors = []
        except ReconcileError as exc:
            errors = [str(exc)]

        remaining_ids = current_ids
        time.sleep(settle_seconds)
    else:
        # Attempts exhausted without an early "nothing left to delete"
        # break -- one final re-list to judge convergence.
        try:
            final_targets = gather_targets(kubeconfig, namespace_prefix, request_timeout_seconds)
            remaining_ids = {target.identifier() for target in final_targets}
            if initial_ids is None:
                initial_ids = set(remaining_ids)
            converged = not remaining_ids
            if not converged and not errors:
                errors = ["cleanup attempts exhausted with residue still present"]
        except ReconcileError as exc:
            errors = [str(exc)]

    result["attempts_used"] = attempt
    if initial_ids is not None and remaining_ids is not None:
        result["deleted"] = sorted(initial_ids - remaining_ids)
        result["remaining"] = sorted(remaining_ids)
    result["no_op"] = bool(initial_ids is not None and not initial_ids and converged)
    result["errors"] = errors
    result["status"] = "ok" if converged else "failed"
    return result


def resolve_kubeconfig(cluster: dict) -> str:
    """Explicit 'kubeconfig' field wins; else derive the deploy-mock-layer.yml
    / execute.yml default of $HOME/.kube/<role>.config."""
    kubeconfig = cluster.get("kubeconfig")
    if kubeconfig:
        return str(kubeconfig)
    role = cluster["role"]
    return os.path.join(os.path.expanduser("~"), ".kube", f"{role}.config")


def reconcile_all(
    clusters: List[dict],
    namespace_prefix: str,
    max_concurrent: int,
    attempts: int,
    settle_seconds: float,
    request_timeout_seconds: float,
) -> List[dict]:
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {}
        for cluster in clusters:
            role = cluster["role"]
            kubeconfig = resolve_kubeconfig(cluster)
            future = executor.submit(
                reconcile_cluster,
                role,
                kubeconfig,
                namespace_prefix,
                attempts,
                settle_seconds,
                request_timeout_seconds,
            )
            futures[future] = role
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
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
        "--scenario", required=True,
        help="Scenario name; must be a key in SCENARIO_NAMESPACE_PREFIXES.",
    )
    parser.add_argument("--summary-file", required=True, help="Output path for the JSON summary.")
    parser.add_argument(
        "--max-concurrent", type=int, default=8,
        help="Maximum number of clusters cleaned up in parallel.",
    )
    parser.add_argument(
        "--attempts", type=int, default=5,
        help="Bounded delete/re-list attempts per cluster before giving up.",
    )
    parser.add_argument(
        "--settle-seconds", type=float, default=15.0,
        help="Sleep between attempts to let namespace/resource termination settle.",
    )
    parser.add_argument(
        "--request-timeout-seconds", type=float, default=30.0,
        help="Bounded timeout for each kubectl invocation.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    namespace_prefix = SCENARIO_NAMESPACE_PREFIXES.get(args.scenario)
    if namespace_prefix is None:
        print(
            f"scenario-cleanup-reconcile: unknown scenario {args.scenario!r}; "
            f"no namespace allowlist entry (known scenarios: "
            f"{sorted(SCENARIO_NAMESPACE_PREFIXES)})",
            file=sys.stderr,
        )
        return 1

    try:
        with open(args.clusters, "r", encoding="utf-8") as handle:
            clusters = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"scenario-cleanup-reconcile: failed to read {args.clusters}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(clusters, list) or not clusters:
        print(
            f"scenario-cleanup-reconcile: {args.clusters} must be a non-empty JSON array",
            file=sys.stderr,
        )
        return 1
    for index, cluster in enumerate(clusters):
        if not isinstance(cluster, dict) or not cluster.get("role"):
            print(f"scenario-cleanup-reconcile: clusters[{index}] missing 'role'", file=sys.stderr)
            return 1

    if args.max_concurrent < 1:
        print("scenario-cleanup-reconcile: --max-concurrent must be >= 1", file=sys.stderr)
        return 1
    if args.attempts < 1:
        print("scenario-cleanup-reconcile: --attempts must be >= 1", file=sys.stderr)
        return 1

    results = reconcile_all(
        clusters,
        namespace_prefix=namespace_prefix,
        max_concurrent=args.max_concurrent,
        attempts=args.attempts,
        settle_seconds=args.settle_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
    )

    failed = sorted(r["role"] for r in results if r["status"] != "ok")
    summary = {
        "schema_version": 1,
        "success": not failed,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scenario": args.scenario,
        "namespace_prefix": namespace_prefix,
        "total_clusters": len(results),
        "healthy_count": len(results) - len(failed),
        "failed_count": len(failed),
        "failed_roles": failed,
        "results": sorted(results, key=lambda r: r["role"]),
    }
    write_summary(args.summary_file, summary)

    print(
        f"scenario-cleanup-reconcile: {summary['healthy_count']}/{summary['total_clusters']} "
        f"cluster(s) clean for {args.scenario}" + (f"; failed: {failed}" if failed else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
