"""Post-execution, file-only scenario evidence validator for clustermesh-scale.

This CLI is deliberately file-only: it never talks to a live cluster. It is
meant to run AFTER `scale.py execute-parallel` (and any host-side stimulus
scripts) have finished writing their per-role report-dir artifacts, and
potentially after cleanup of the underlying clusters has already started —
so any live kubectl/API call here would be unreliable. Instead it re-derives
"did the intended stimulus actually run, and does the required evidence
exist" purely from files already written under `--report-dir`
(`<cl2_report_dir>/<scenario>/<role>/...`), `--worker-summary`
(execute-parallel's per-cluster pass/fail summary), and the scenario's own
configured expectations (cluster count, target role, probe counts, etc.).

Design notes:
  * Ordinary JUnit SLI failures (failures/errors counts in junit.xml) are
    measurement data, not evidence-contract violations — a scenario can be
    "the stimulus ran and evidence exists" valid even though its CL2
    measurements show a regression. Only a handful of scenario-specific
    CRITICAL testcases (see `_check_pod_churn_combined`) are treated as
    contract-invalidating on failure.
  * Every check is recorded (pass or fail) in `checks[]` so postmortem
    tooling can see exactly what was inspected, not just the verdict.
  * The output is schema-versioned and atomically written. Expected malformed
    or missing evidence is recorded as a failing check; unexpected programming
    errors are allowed to fail loudly rather than being converted into a
    success-shaped result.

Exit codes:
  0 - every check passed (measurement_valid == true).
  1 - the evidence contract failed (measurement_valid == false); the
      output file is still written with the full check/reason detail.
  2 - invalid invocation (bad CLI arguments, or the output file itself
      could not be written).
"""
# pylint: disable=too-many-lines

import argparse
import glob
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from xml.dom import minidom
from xml.parsers.expat import ExpatError

SCHEMA_VERSION = 1

# Scenarios that resolve a single designated "target role" (the cluster the
# host-side stimulus script acted on) rather than aggregating over every
# succeeded worker role.
TARGET_ROLE_SCENARIOS = {
    "apiserver-failure",
    "isolation",
    "node-churn-scale",
    "node-churn-replace",
    "node-churn-combined",
}

NODE_CHURN_SCENARIOS = {"node-churn-scale", "node-churn-replace", "node-churn-combined"}

# pod-churn-combined.yaml step names (see that CL2 config's step `name:`
# fields) whose junit testcase must exist and be failure/error-free — they
# are the CL2-side proof that Phase A's scale-cycle churn and Phase B's kill
# loop both converged, i.e. the stimulus actually completed and didn't just
# get skipped/timed out silently.
POD_CHURN_CRITICAL_TESTCASE_SUBSTRINGS = (
    "post-scale-cycle",  # "Wait for post-scale-cycle pods to be Running"
    "post-kill",  # "Wait for post-kill pods to be Running"
)

KVSTORE_DURATION_METRIC_NAME = "ClusterMesh Kvstore Operation Duration"

# Every verdict-driving saturation signal, keyed by the same signal name
# scale.py's `_emit_saturation_profile_rows.signal_map` uses, mapped to the
# (CL2 metricName, metric label) pair that identifies its per-rung
# GenericPrometheusQuery file. This MUST stay in sync with scale.py's
# `signal_map` / `SATURATION_THRESHOLDS` — those five signals are exactly
# the ones scale.py itself requires for a rung to be `measurement_valid`
# (see `rung_completed` there). A rung whose CL2 output is missing any one
# of these must independently be flagged measurement-invalid here too,
# rather than trusting scale.py's own SaturationRung row — the evidence
# validator's job is to re-derive pass/fail from raw files, not from
# scale.py's self-reported verdict. Context-only signals (queue_size_max,
# observed_event_rate_p99) are intentionally excluded: they inform
# dashboards but never gate the upper-bound verdict.
REQUIRED_SATURATION_SIGNALS = {
    "latency_p99_ms": (KVSTORE_DURATION_METRIC_NAME, "Perc99"),
    "queue_size_perc99": ("ClusterMesh Kvstore Sync Queue Size", "Perc99"),
    "apiserver_max_cpu_cores": ("ClusterMesh APIServer Pod CPU", "PerPodMax"),
    "mesh_failure_rate_max": ("ClusterMesh Remote Cluster Failure Rate", "Max"),
    "etcd_commit_p99_ms": ("ClusterMesh Etcd Backend Write Duration", "Perc99"),
}


@dataclass
class Check:
    """One evaluated evidence check."""

    name: str
    passed: bool
    detail: str = ""


class EvidenceContext:
    """Accumulates checks and useful counts for one validation run."""

    def __init__(self):
        self.checks: List[Check] = []
        self.counts: Dict[str, Any] = {}

    def add(self, name: str, passed: bool, detail: str = "") -> bool:
        passed = bool(passed)
        self.checks.append(Check(name=name, passed=passed, detail=detail))
        return passed

    @property
    def valid(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def reasons(self) -> List[str]:
        return [
            f"{check.name}: {check.detail}" if check.detail else check.name
            for check in self.checks
            if not check.passed
        ]

    def to_dict(self) -> List[Dict[str, Any]]:
        return [
            {"name": check.name, "passed": check.passed, "detail": check.detail}
            for check in self.checks
        ]


# ---------------------------------------------------------------------------
# Small file-parsing helpers. Every one of these is pure and side-effect
# free (no network, no subprocess) — this module only ever reads files.
# ---------------------------------------------------------------------------

def _load_json_file(path: str) -> Tuple[Optional[Any], Optional[str]]:
    """Return (data, error). Exactly one of the two is None."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return None, f"file not found: {path}"
    except OSError as error:
        return None, f"could not read {path}: {error}"
    if not raw.strip():
        return None, f"file is empty: {path}"
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as error:
        return None, f"malformed JSON in {path}: {error}"


def _load_jsonl_file(path: str) -> Tuple[List[Any], int]:
    """Return (parsed_rows, malformed_line_count) for a JSONL file."""
    rows: List[Any] = []
    malformed = 0
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1
    return rows, malformed


def _parse_junit(path: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Return (testsuites, error).

    Each testsuite dict is {"name": str, "testcases": [{"name": str,
    "failed": bool}, ...]}. `failed` is true if the testcase has a
    <failure> or <error> child — both are contract-relevant for the
    scenario-specific "critical testcase" checks even though ordinary
    SLI failures/errors don't otherwise invalidate the scenario.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except FileNotFoundError:
        return None, f"file not found: {path}"
    except OSError as error:
        return None, f"could not read {path}: {error}"
    if not content.strip():
        return None, f"junit.xml is empty: {path}"
    try:
        dom = minidom.parseString(content)  # nosec B318 - trusted local CL2 output
    except ExpatError as error:
        return None, f"malformed XML in {path}: {error}"

    suite_nodes = dom.getElementsByTagName("testsuite")
    if not suite_nodes:
        return None, f"no <testsuite> element found in {path}"

    suites = []
    for suite_node in suite_nodes:
        testcases = []
        for testcase_node in suite_node.getElementsByTagName("testcase"):
            failed = bool(testcase_node.getElementsByTagName("failure")) or bool(
                testcase_node.getElementsByTagName("error")
            )
            testcases.append(
                {"name": testcase_node.getAttribute("name"), "failed": failed}
            )
        if testcases:
            suites.append({"name": suite_node.getAttribute("name"), "testcases": testcases})

    if not suites:
        return None, f"no <testcase> element found in any <testsuite> in {path}"
    return suites, None


def _read_metric_value(data: Any, metric_label: str) -> Optional[float]:
    """Extract a numeric metric label from a GenericPrometheusQuery JSON.

    Supports both known CL2 dataItem shapes (see scale.py's
    `_emit_saturation_profile_rows._read_metric` for the authoritative
    description of these two shapes):
      (A) {"dataItems": [{"data": {"Perc99": 0.5, ...}}]}
      (B) {"dataItems": [{"labels": {"Metric": "Perc99"}, "data": {"value": 0.5}}]}
    """
    if not isinstance(data, dict):
        return None
    for item in data.get("dataItems", []) or []:
        if not isinstance(item, dict):
            continue
        item_data = item.get("data") or {}
        if not isinstance(item_data, dict):
            continue
        if metric_label in item_data and not isinstance(
            item_data[metric_label], (dict, list)
        ):
            value = item_data[metric_label]
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        labels = item.get("labels") or {}
        if labels.get("Metric") == metric_label:
            value = item_data.get("value")
            if value in (None, ""):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _find_metric_value(
    role_dir: str, metric_name: str, metric_label: str
) -> Optional[float]:
    """Find a CL2 GenericPrometheusQuery file by metric name and read a label."""
    try:
        entries = os.listdir(role_dir)
    except OSError:
        return None
    compact_metric = metric_name.replace(" ", "")
    matches = [
        entry
        for entry in entries
        if entry.endswith(".json")
        and (
            entry.startswith(f"GenericPrometheusQuery {metric_name}")
            or entry.startswith(f"GenericPrometheusQuery_{compact_metric}")
        )
    ]
    for entry in sorted(matches):
        data, error = _load_json_file(os.path.join(role_dir, entry))
        if error is None:
            value = _read_metric_value(data, metric_label)
            if value is not None:
                return value
    return None


def _find_rung_metric_value(
    role_dir: str, entries: List[str], rung_suffix: str, metric_name: str, metric_label: str
) -> Optional[float]:
    """Locate a rung's GenericPrometheusQuery file by metric name and read a label.

    Matches both CL2 filename conventions (see scale.py's `_find_file`):
    the production "space separated" form and the compact/mock form. Callers
    MUST anchor on `rung_suffix` (e.g. "Rung1_") rather than a bare substring
    match — otherwise "Rung1" would also match "Rung10"/"Rung11"/... filenames
    once there are >= 11 rungs, silently attributing a later rung's file to
    an earlier one (see the Rung1-vs-Rung10+ regression test).
    """
    prod_prefix = f"GenericPrometheusQuery {metric_name} {rung_suffix}_"
    compact_metric = metric_name.replace(" ", "")
    compact_prefix = f"GenericPrometheusQuery_{compact_metric}{rung_suffix}_"
    matches = [
        entry
        for entry in entries
        if (entry.startswith(prod_prefix) or entry.startswith(compact_prefix))
        and entry.endswith(".json")
    ]
    for fname in matches:
        data, error = _load_json_file(os.path.join(role_dir, fname))
        if error:
            continue
        value = _read_metric_value(data, metric_label)
        if value is not None:
            return value
    return None


def _find_kvstore_duration_perc99(
    role_dir: str, entries: List[str], rung_suffix: str
) -> Optional[float]:
    """Locate the rung's kvstore-operation-duration file and read Perc99."""
    return _find_rung_metric_value(
        role_dir, entries, rung_suffix, KVSTORE_DURATION_METRIC_NAME, "Perc99"
    )


# ---------------------------------------------------------------------------
# Common contract: worker-summary shape + per-succeeded-role junit sanity.
# ---------------------------------------------------------------------------

def _run_common_checks(
    ctx: EvidenceContext, worker_summary_path: str, cluster_count: int, report_dir: str
) -> Tuple[List[str], List[str]]:
    """Validate the worker-summary contract and per-role junit sanity.

    Returns (succeeded_roles, failed_roles) — both sorted, deduplicated,
    and empty if the worker summary itself could not be trusted.
    """
    data, error = _load_json_file(worker_summary_path)
    if error:
        ctx.add("worker_summary_valid_json", False, error)
        return [], []
    ctx.add("worker_summary_valid_json", True)

    if not isinstance(data, dict):
        ctx.add("worker_summary_is_object", False, f"expected a JSON object, got {type(data).__name__}")
        return [], []

    total_workers = data.get("total_workers")
    ctx.add(
        "worker_total_matches_cluster_count",
        isinstance(total_workers, int) and total_workers == cluster_count,
        f"total_workers={total_workers!r}, expected cluster_count={cluster_count}",
    )

    succeeded_roles_raw = data.get("succeeded_roles")
    failed_roles_raw = data.get("failed_roles")
    roles_are_lists = isinstance(succeeded_roles_raw, list) and isinstance(failed_roles_raw, list)
    ctx.add(
        "worker_summary_roles_are_lists",
        roles_are_lists,
        "succeeded_roles and failed_roles must both be JSON arrays",
    )
    if not roles_are_lists:
        return [], []

    problems = []
    succeeded_roles_valid = all(
        isinstance(role, str) and role for role in succeeded_roles_raw
    )
    failed_roles_valid = all(
        isinstance(role, str) and role for role in failed_roles_raw
    )
    if not succeeded_roles_valid:
        problems.append("succeeded_roles must contain only nonempty strings")
    if not failed_roles_valid:
        problems.append("failed_roles must contain only nonempty strings")
    succeeded_roles = (
        sorted(set(succeeded_roles_raw)) if succeeded_roles_valid else []
    )
    failed_roles = sorted(set(failed_roles_raw)) if failed_roles_valid else []
    if len(succeeded_roles) != len(succeeded_roles_raw):
        problems.append("succeeded_roles contains duplicate entries")
    if len(failed_roles) != len(failed_roles_raw):
        problems.append("failed_roles contains duplicate entries")
    succeeded_count = data.get("succeeded_count")
    if not isinstance(succeeded_count, int):
        problems.append("succeeded_count must be an integer")
    elif succeeded_count != len(succeeded_roles):
        problems.append(
            f"succeeded_count={succeeded_count} != len(succeeded_roles)={len(succeeded_roles)}"
        )
    failed_count = data.get("failed_count")
    if not isinstance(failed_count, int):
        problems.append("failed_count must be an integer")
    elif failed_count != len(failed_roles):
        problems.append(
            f"failed_count={failed_count} != len(failed_roles)={len(failed_roles)}"
        )
    overlap = sorted(set(succeeded_roles) & set(failed_roles))
    if overlap:
        problems.append(f"role(s) present in both succeeded_roles and failed_roles: {overlap}")
    if isinstance(total_workers, int) and len(succeeded_roles) + len(failed_roles) != total_workers:
        problems.append(
            "len(succeeded_roles) + len(failed_roles) does not sum to total_workers"
        )
    telemetry_failed_roles_raw = data.get("telemetry_failed_roles", [])
    telemetry_failed_count = data.get("telemetry_failed_count", 0)
    if not isinstance(telemetry_failed_roles_raw, list) or not all(
        isinstance(role, str) and role for role in telemetry_failed_roles_raw
    ):
        problems.append(
            "telemetry_failed_roles must contain only nonempty strings"
        )
        telemetry_failed_roles = []
    else:
        telemetry_failed_roles = sorted(set(telemetry_failed_roles_raw))
        if len(telemetry_failed_roles) != len(telemetry_failed_roles_raw):
            problems.append("telemetry_failed_roles contains duplicate entries")
    if not isinstance(telemetry_failed_count, int):
        problems.append("telemetry_failed_count must be an integer")
    elif telemetry_failed_count != len(telemetry_failed_roles):
        problems.append(
            "telemetry_failed_count does not match "
            "telemetry_failed_roles length"
        )
    telemetry_without_workload = sorted(
        set(telemetry_failed_roles) - set(succeeded_roles)
    )
    if telemetry_without_workload:
        problems.append(
            "telemetry_failed_roles must be workload-succeeded roles: "
            f"{telemetry_without_workload}"
        )
    ctx.add("worker_summary_counts_internally_consistent", not problems, "; ".join(problems))

    ctx.counts["total_workers"] = total_workers
    ctx.counts["succeeded_role_count"] = len(succeeded_roles)
    ctx.counts["failed_role_count"] = len(failed_roles)
    ctx.counts["telemetry_failed_role_count"] = len(telemetry_failed_roles)
    ctx.counts["telemetry_failed_roles"] = telemetry_failed_roles

    valid_junit_roles = 0
    for role in succeeded_roles:
        junit_path = os.path.join(report_dir, role, "junit.xml")
        _, junit_error = _parse_junit(junit_path)
        if junit_error:
            ctx.add(f"junit_valid[{role}]", False, junit_error)
            continue
        ctx.add(f"junit_valid[{role}]", True)
        valid_junit_roles += 1
    ctx.counts["junit_valid_role_count"] = valid_junit_roles

    return succeeded_roles, failed_roles


# ---------------------------------------------------------------------------
# Scenario-specific contracts.
# ---------------------------------------------------------------------------

def _check_propagation_probe(
    ctx: EvidenceContext,
    report_dir: str,
    succeeded_roles: List[str],
    cluster_count: int,
    probe_count: int,
    peer_sample: int,
) -> None:
    if not succeeded_roles:
        ctx.add("propagation_succeeded_roles_present", False, "no succeeded roles to search for evidence")
        return

    candidates = []
    for role in succeeded_roles:
        path = os.path.join(report_dir, role, "PropagationTimings.jsonl")
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            candidates.append(path)
    ctx.add(
        "propagation_exactly_one_nonempty_file",
        len(candidates) == 1,
        f"found {len(candidates)} nonempty PropagationTimings.jsonl under role dirs (expected exactly 1): {candidates}",
    )
    if len(candidates) != 1:
        return
    path = candidates[0]

    try:
        rows, malformed = _load_jsonl_file(path)
    except OSError as error:
        ctx.add("propagation_file_readable", False, str(error))
        return
    ctx.add("propagation_no_malformed_lines", malformed == 0, f"{malformed} malformed JSON line(s) in {path}")

    required_fields = ("src_cluster", "peer_cluster", "probe_id", "peer_timed_out")
    bad_rows = 0
    probe_ids = set()
    for row in rows:
        if not isinstance(row, dict):
            bad_rows += 1
            continue
        missing = [f for f in required_fields if f not in row]
        src_ok = isinstance(row.get("src_cluster"), str) and row.get("src_cluster")
        peer_ok = isinstance(row.get("peer_cluster"), str) and row.get("peer_cluster")
        probe_ok = isinstance(row.get("probe_id"), str) and row.get("probe_id")
        timed_out_ok = isinstance(row.get("peer_timed_out"), bool)
        if missing or not (src_ok and peer_ok and probe_ok and timed_out_ok):
            bad_rows += 1
        else:
            probe_ids.add(row["probe_id"])
    ctx.add(
        "propagation_rows_have_required_fields",
        bad_rows == 0,
        f"{bad_rows} of {len(rows)} row(s) missing/invalid src_cluster/peer_cluster/probe_id/peer_timed_out",
    )

    expected_peers_per_probe = max(cluster_count - 1, 0)
    if peer_sample > 0:
        expected_peers_per_probe = min(expected_peers_per_probe, peer_sample)
    expected_rows = probe_count * expected_peers_per_probe
    ctx.add(
        "propagation_row_count_matches_expected",
        len(rows) == expected_rows,
        f"observed {len(rows)} row(s), expected {expected_rows} "
        f"(probe_count={probe_count} * min(cluster_count-1={cluster_count - 1}, peer_sample={peer_sample}))",
    )
    ctx.add(
        "propagation_distinct_probe_ids_matches_expected",
        len(probe_ids) == probe_count,
        f"observed {len(probe_ids)} distinct probe_id value(s), expected {probe_count}",
    )

    ctx.counts["propagation_rows_total"] = len(rows)
    ctx.counts["propagation_distinct_probe_ids"] = len(probe_ids)
    ctx.counts["propagation_expected_rows"] = expected_rows


def _check_event_throughput(ctx: EvidenceContext, report_dir: str, succeeded_roles: List[str]) -> None:
    if not succeeded_roles:
        ctx.add("event_throughput_succeeded_roles_present", False, "no succeeded roles to search for evidence")
        return

    verified_roles = 0
    for role in succeeded_roles:
        path = os.path.join(report_dir, role, "EventThroughputEvidence.json")
        data, error = _load_json_file(path)
        if error:
            ctx.add(f"event_throughput_evidence_valid[{role}]", False, error)
            continue
        if not isinstance(data, dict):
            ctx.add(f"event_throughput_evidence_valid[{role}]", False, "evidence file is not a JSON object")
            continue

        problems = []
        if data.get("capture_valid") is not True:
            problems.append("capture_valid is not true")
        if data.get("restart_valid") is not True:
            problems.append("restart_valid is not true")

        pre = data.get("pre_restart") or {}
        post = data.get("post_restart") or {}

        expected_deployments = pre.get("expected_deployment_count")
        expected_pods = pre.get("expected_pod_count")
        if not isinstance(expected_deployments, int) or not isinstance(expected_pods, int):
            problems.append("pre_restart is missing expected_deployment_count/expected_pod_count")
        else:
            for phase_name, phase in (("pre_restart", pre), ("post_restart", post)):
                if phase.get("deployment_count") != expected_deployments:
                    problems.append(
                        f"{phase_name}.deployment_count={phase.get('deployment_count')!r} "
                        f"!= expected_deployment_count={expected_deployments}"
                    )
                if phase.get("pod_count") != expected_pods:
                    problems.append(
                        f"{phase_name}.pod_count={phase.get('pod_count')!r} != expected_pod_count={expected_pods}"
                    )
                if phase.get("ready_pod_count") != expected_pods:
                    problems.append(
                        f"{phase_name}.ready_pod_count={phase.get('ready_pod_count')!r} "
                        f"!= expected_pod_count={expected_pods}"
                    )

        if post.get("restart_generation_verified") is not True:
            problems.append("post_restart.restart_generation_verified is not true")

        # A Pod UID snapshot is only trustworthy as proof of "every expected
        # pod was actually observed, each exactly once" when it has EXACTLY
        # expected_pod_count entries AND exactly expected_pod_count distinct
        # UIDs. Checking only "non-empty" (as before) would false-pass a
        # partial kubectl listing (fewer UIDs than expected pods) or a
        # duplicate-UID listing (same pod counted twice, masking a missing
        # pod) as long as the list wasn't empty. Re-derive both counts from
        # the actual `pod_uids` array rather than trusting the sidecar's
        # self-reported `uid_count`/`unique_uid_count` alone, but also
        # cross-check against those reported counts (when present) and the
        # query-success flag so a query that failed can't be laundered into
        # a "valid" snapshot merely because its (empty/stale) UID list
        # happens to look consistent.
        pre_uids = pre.get("pod_uids")
        post_uids = post.get("pod_uids")
        if not isinstance(pre_uids, list):
            problems.append("pre_restart.pod_uids is missing or not a list")
            pre_uids = []
        if not isinstance(post_uids, list):
            problems.append("post_restart.pod_uids is missing or not a list")
            post_uids = []

        if isinstance(expected_pods, int):
            for phase_name, phase, uids in (
                ("pre_restart", pre, pre_uids),
                ("post_restart", post, post_uids),
            ):
                uid_query_success = ((phase.get("query_success") or {}).get("pod_uids"))
                if uid_query_success is not True:
                    problems.append(f"{phase_name}.query_success.pod_uids is not true")

                observed_uid_count = phase.get("uid_count")
                if observed_uid_count != expected_pods:
                    problems.append(
                        f"{phase_name}.uid_count={observed_uid_count!r} != expected_pod_count={expected_pods}"
                    )
                if len(uids) != expected_pods:
                    problems.append(
                        f"{phase_name}.pod_uids has {len(uids)} entr(y/ies), expected exactly {expected_pods}"
                    )

                observed_unique_uid_count = phase.get("unique_uid_count")
                if observed_unique_uid_count != expected_pods:
                    problems.append(
                        f"{phase_name}.unique_uid_count={observed_unique_uid_count!r} "
                        f"!= expected_pod_count={expected_pods}"
                    )
                distinct = len(set(uids))
                if distinct != expected_pods:
                    problems.append(
                        f"{phase_name}.pod_uids has {distinct} unique value(s) (duplicates present), "
                        f"expected exactly {expected_pods} unique UIDs"
                    )

        overlap = set(pre_uids) & set(post_uids)
        if overlap:
            problems.append(f"{len(overlap)} pod UID(s) overlap between pre_restart and post_restart")

        passed = not problems
        ctx.add(f"event_throughput_evidence_valid[{role}]", passed, "; ".join(problems))
        if passed:
            verified_roles += 1

    ctx.counts["event_throughput_roles_verified"] = verified_roles


def _check_pod_churn_combined(ctx: EvidenceContext, report_dir: str, succeeded_roles: List[str]) -> None:
    if not succeeded_roles:
        ctx.add("pod_churn_succeeded_roles_present", False, "no succeeded roles to search for evidence")
        return

    verified_roles = 0
    for role in succeeded_roles:
        role_dir = os.path.join(report_dir, role)
        data, error = _load_json_file(os.path.join(role_dir, "PodChurnEvidence.json"))
        if error:
            ctx.add(f"pod_churn_evidence_valid[{role}]", False, error)
        else:
            problems = []
            if not isinstance(data, dict):
                problems.append("evidence file is not a JSON object")
            else:
                if data.get("stimulus_valid") is not True:
                    problems.append("stimulus_valid is not true")
                rounds = data.get("rounds")
                if not (isinstance(rounds, int) and rounds > 0):
                    problems.append(f"rounds={rounds!r} must be an int > 0")
                killed_total = data.get("killed_total")
                if not (isinstance(killed_total, int) and killed_total > 0):
                    problems.append(f"killed_total={killed_total!r} must be an int > 0")
            passed = not problems
            ctx.add(f"pod_churn_evidence_valid[{role}]", passed, "; ".join(problems))
            if passed:
                verified_roles += 1

        # Critical convergence testcases: these must exist and carry no
        # failure/error child, independent of ordinary SLI failure counts.
        suites, junit_error = _parse_junit(os.path.join(role_dir, "junit.xml"))
        if junit_error:
            ctx.add(f"pod_churn_critical_testcases_found[{role}]", False, junit_error)
            continue
        all_testcases = [tc for suite in suites for tc in suite["testcases"]]
        for substring in POD_CHURN_CRITICAL_TESTCASE_SUBSTRINGS:
            matches = [tc for tc in all_testcases if substring in tc["name"]]
            if not matches:
                ctx.add(
                    f"pod_churn_critical_testcase_present[{role}:{substring}]",
                    False,
                    f"no testcase name containing {substring!r} found in junit.xml",
                )
                continue
            ctx.add(f"pod_churn_critical_testcase_present[{role}:{substring}]", True)
            failing = [tc for tc in matches if tc["failed"]]
            ctx.add(
                f"pod_churn_critical_testcase_passed[{role}:{substring}]",
                not failing,
                f"{len(failing)} of {len(matches)} matching testcase(s) reported failure/error",
            )

    ctx.counts["pod_churn_roles_verified"] = verified_roles


def _check_apiserver_failure(ctx: EvidenceContext, report_dir: str, target_role: str) -> None:
    if not target_role:
        ctx.add("apiserver_failure_target_role_resolved", False, "--target-role was not provided")
        return
    role_dir = os.path.join(report_dir, target_role)
    candidates = sorted(glob.glob(os.path.join(role_dir, "ApiserverFailureTimings_*.json")))
    if len(candidates) != 1:
        ctx.add(
            "apiserver_failure_exactly_one_timing_file",
            False,
            f"found {len(candidates)} ApiserverFailureTimings_*.json under {role_dir} (expected exactly 1)",
        )
        return
    ctx.add("apiserver_failure_exactly_one_timing_file", True)

    data, error = _load_json_file(candidates[0])
    if error:
        ctx.add("apiserver_failure_timing_file_valid_json", False, error)
        return
    if not isinstance(data, dict):
        ctx.add(
            "apiserver_failure_timing_file_is_object",
            False,
            f"expected a JSON object, got {type(data).__name__}",
        )
        return
    ctx.add("apiserver_failure_timing_file_valid_json", True)

    ctx.add("apiserver_failure_recovered", data.get("recovered") is True, f"recovered={data.get('recovered')!r}")

    killed_uid = data.get("killed_pod_uid")
    replacement_uid = data.get("replacement_pod_uid")
    nonempty = (
        isinstance(killed_uid, str)
        and killed_uid
        and isinstance(replacement_uid, str)
        and replacement_uid
    )
    ctx.add(
        "apiserver_failure_uids_nonempty",
        nonempty,
        f"killed_pod_uid={killed_uid!r}, replacement_pod_uid={replacement_uid!r}",
    )
    ctx.add(
        "apiserver_failure_uids_differ",
        bool(nonempty) and killed_uid != replacement_uid,
        "killed_pod_uid and replacement_pod_uid must differ",
    )


def _check_policy_scale(ctx: EvidenceContext, report_dir: str, succeeded_roles: List[str]) -> None:
    if not succeeded_roles:
        ctx.add("policy_scale_succeeded_roles_present", False, "no succeeded roles to search for evidence")
        return

    verified_roles = 0
    repair_roles = []
    for role in succeeded_roles:
        data, error = _load_json_file(os.path.join(report_dir, role, "PolicyScaleEvidence.json"))
        if error:
            ctx.add(f"policy_scale_evidence_valid[{role}]", False, error)
            continue
        if not isinstance(data, dict):
            ctx.add(f"policy_scale_evidence_valid[{role}]", False, "evidence file is not a JSON object")
            continue

        problems = []
        active = data.get("active") if isinstance(data.get("active"), dict) else {}
        deleted = data.get("deleted") if isinstance(data.get("deleted"), dict) else {}

        if active.get("verified") is not True:
            problems.append("active.verified is not true")
        expected_total = active.get("expected_total")
        observed_total = active.get("observed_total")
        if not isinstance(expected_total, int) or observed_total != expected_total:
            problems.append(
                f"active.observed_total={observed_total!r} != active.expected_total={expected_total!r}"
            )

        if deleted.get("verified") is not True:
            problems.append("deleted.verified is not true")
        if deleted.get("observed_count") != 0:
            problems.append(f"deleted.observed_count={deleted.get('observed_count')!r} != 0")
        repair_requested = deleted.get("repair_delete_requested") is True
        if repair_requested:
            repair_roles.append(role)
        ctx.add(
            f"policy_scale_delete_path[{role}]",
            True,
            (
                "evidence repair re-issued label-scoped CNP deletion"
                if repair_requested
                else "primary CL2 deletion converged without repair"
            ),
        )

        policy_samples = _find_metric_value(
            os.path.join(report_dir, role),
            "Cilium Policy Implementation Delay",
            "TotalSamples",
        )
        if policy_samples is None or policy_samples <= 0:
            problems.append(
                "Cilium Policy Implementation Delay TotalSamples is missing or not positive"
            )
        endpoint_regenerations = _find_metric_value(
            os.path.join(report_dir, role),
            "Cilium Endpoint Regenerations",
            "TotalIncrease",
        )
        if endpoint_regenerations is None or endpoint_regenerations <= 0:
            problems.append(
                "Cilium Endpoint Regenerations TotalIncrease is missing or not positive"
            )

        passed = not problems
        ctx.add(f"policy_scale_evidence_valid[{role}]", passed, "; ".join(problems))
        if passed:
            verified_roles += 1

    ctx.counts["policy_scale_roles_verified"] = verified_roles
    ctx.counts["policy_scale_delete_repair_roles"] = sorted(repair_roles)


def _check_isolation(ctx: EvidenceContext, report_dir: str, target_role: str) -> None:
    if not target_role:
        ctx.add("isolation_target_role_resolved", False, "--target-role was not provided")
        return
    role_dir = os.path.join(report_dir, target_role)
    candidates = sorted(glob.glob(os.path.join(role_dir, "IsolationChurnTimings_*.json")))
    if len(candidates) != 1:
        ctx.add(
            "isolation_exactly_one_timing_file",
            False,
            f"found {len(candidates)} IsolationChurnTimings_*.json under {role_dir} (expected exactly 1)",
        )
        return
    ctx.add("isolation_exactly_one_timing_file", True)

    data, error = _load_json_file(candidates[0])
    if error:
        ctx.add("isolation_timing_file_valid_json", False, error)
        return
    if not isinstance(data, dict):
        ctx.add(
            "isolation_timing_file_is_object",
            False,
            f"expected a JSON object, got {type(data).__name__}",
        )
        return
    ctx.add("isolation_timing_file_valid_json", True)

    ctx.add("isolation_stimulus_valid", data.get("stimulus_valid") is True, f"stimulus_valid={data.get('stimulus_valid')!r}")
    ctx.add(
        "isolation_killer_exit_code_zero",
        data.get("killer_exit_code") == 0,
        f"killer_exit_code={data.get('killer_exit_code')!r}",
    )
    rounds = data.get("rounds")
    ctx.add("isolation_rounds_positive", isinstance(rounds, int) and rounds > 0, f"rounds={rounds!r}")
    killed_total = data.get("killed_total")
    ctx.add(
        "isolation_killed_total_positive",
        isinstance(killed_total, int) and killed_total > 0,
        f"killed_total={killed_total!r}",
    )


# Candidate field names node-churner.sh might expose for the configured
# replace count. None are guaranteed to exist — see the "do not invent
# unavailable fields" contract requirement; the check below is skipped
# entirely (not force-passed) when none of these are present.
_NODE_CHURN_REPLACE_COUNT_FIELDS = (
    "node_replace_batch_size",
    "replace_count",
    "target_replace_count",
    "configured_replace_count",
    "replace_node_count",
)


def _check_node_churn(ctx: EvidenceContext, report_dir: str, target_role: str, scenario: str) -> None:
    if not target_role:
        ctx.add("node_churn_target_role_resolved", False, "--target-role was not provided")
        return
    role_dir = os.path.join(report_dir, target_role)
    candidates = sorted(glob.glob(os.path.join(role_dir, "NodeChurnTimings_*.json")))
    if len(candidates) != 1:
        ctx.add(
            "node_churn_exactly_one_timing_file",
            False,
            f"found {len(candidates)} NodeChurnTimings_*.json under {role_dir} (expected exactly 1)",
        )
        return
    ctx.add("node_churn_exactly_one_timing_file", True)

    data, error = _load_json_file(candidates[0])
    if error:
        ctx.add("node_churn_timing_file_valid_json", False, error)
        return
    if not isinstance(data, dict):
        ctx.add(
            "node_churn_timing_file_is_object",
            False,
            f"expected a JSON object, got {type(data).__name__}",
        )
        return
    ctx.add("node_churn_timing_file_valid_json", True)

    ctx.add("node_churn_scenario_valid", data.get("scenario_valid") is True, f"scenario_valid={data.get('scenario_valid')!r}")
    ctx.add(
        "node_churn_cleanup_not_failed",
        data.get("cleanup_failed") is False,
        f"cleanup_failed={data.get('cleanup_failed')!r}",
    )
    ctx.add(
        "node_churn_not_truncated",
        data.get("truncated") is False,
        f"truncated={data.get('truncated')!r}",
    )

    ops = data.get("ops")
    if not isinstance(ops, list) or not ops:
        ctx.add("node_churn_operations_present", False, "'ops' array is missing or empty")
        return
    ctx.add("node_churn_operations_present", True)
    ctx.counts["node_churn_operation_count"] = len(ops)

    failed_ops = [
        op for op in ops if not isinstance(op, dict) or op.get("succeeded") is not True
    ]
    ctx.add(
        "node_churn_all_operations_succeeded",
        not failed_ops,
        f"{len(failed_ops)} of {len(ops)} recorded operation(s) did not succeed",
    )

    if scenario in ("node-churn-replace", "node-churn-combined"):
        replace_wait_ops = [
            op for op in ops if isinstance(op, dict) and op.get("op_type") == "replace_wait"
        ]
        if not replace_wait_ops:
            ctx.add("node_churn_replace_wait_present", False, "no replace_wait operation recorded")
        else:
            ctx.add("node_churn_replace_wait_present", True)
            last_replace_wait = replace_wait_ops[-1]
            ctx.add(
                "node_churn_replace_wait_succeeded",
                last_replace_wait.get("succeeded") is True,
                f"replace_wait succeeded={last_replace_wait.get('succeeded')!r}",
            )

            configured_count = None
            for field_name in _NODE_CHURN_REPLACE_COUNT_FIELDS:
                value = data.get(field_name)
                if isinstance(value, int):
                    configured_count = value
                    break
            ctx.counts["node_churn_replace_count_field_present"] = configured_count is not None
            if configured_count is not None:
                new_node_count = last_replace_wait.get("new_node_count")
                ctx.add(
                    "node_churn_replace_new_node_count_meets_configured",
                    isinstance(new_node_count, int) and new_node_count >= configured_count,
                    f"new_node_count={new_node_count!r}, configured replace count={configured_count}",
                )


def _check_upper_bound(
    ctx: EvidenceContext, report_dir: str, succeeded_roles: List[str], saturation_qps_list: str
) -> None:
    if not succeeded_roles:
        ctx.add("upper_bound_succeeded_roles_present", False, "no succeeded roles to search for evidence")
        return
    if not saturation_qps_list.strip():
        ctx.add(
            "upper_bound_qps_list_provided",
            False,
            "--saturation-qps-list is required to determine the configured rung count",
        )
        return
    try:
        qps_list = [int(value) for value in saturation_qps_list.split(",") if value.strip()]
    except ValueError as error:
        ctx.add("upper_bound_qps_list_parseable", False, str(error))
        return
    if not qps_list:
        ctx.add("upper_bound_qps_list_nonempty", False, "--saturation-qps-list parsed to an empty rung list")
        return
    ctx.counts["upper_bound_rung_count"] = len(qps_list)

    for role in succeeded_roles:
        role_dir = os.path.join(report_dir, role)
        try:
            entries = sorted(os.listdir(role_dir))
        except OSError as error:
            ctx.add(f"upper_bound_role_dir_readable[{role}]", False, str(error))
            continue

        for rung_idx in range(len(qps_list)):
            suffix = f"Rung{rung_idx}"
            # CL2 always emits the rung marker as "Rung<N>_..." (see
            # `_find_kvstore_duration_perc99` above) — matching on the bare
            # `suffix in entry` substring would let "Rung1" match filenames
            # actually belonging to "Rung10".."Rung19" etc. once there are
            # >= 11 rungs, silently attributing a later rung's file to an
            # earlier one. Anchor on the trailing underscore that always
            # immediately follows the rung index in real filenames.
            rung_marker = f"{suffix}_"
            rung_files = [
                entry
                for entry in entries
                if entry.startswith("GenericPrometheusQuery") and rung_marker in entry and entry.endswith(".json")
            ]
            parseable = [
                entry for entry in rung_files if _load_json_file(os.path.join(role_dir, entry))[1] is None
            ]
            ctx.add(
                f"upper_bound_rung_measurement_present[{role}:{suffix}]",
                bool(parseable),
                f"no parseable GenericPrometheusQuery*{suffix}*.json under {role_dir} "
                "(missing later-rung data is measurement-invalid, not a saturation verdict)",
            )

            perc99 = _find_kvstore_duration_perc99(role_dir, entries, suffix)
            ctx.add(
                f"upper_bound_kvstore_duration_perc99[{role}:{suffix}]",
                perc99 is not None,
                f"no parseable '{KVSTORE_DURATION_METRIC_NAME}' file with numeric Perc99 for {suffix}",
            )

            # A rung is only a valid upper-bound measurement when EVERY
            # verdict-driving signal is present and numeric — matching
            # scale.py's own `rung_completed` gate. Independently
            # re-checking each of `REQUIRED_SATURATION_SIGNALS` here (not
            # just latency, and not just deferring to scale.py's own
            # "rung_completed"/"measurement_valid" self-report) means a CL2
            # output tree that silently dropped e.g. the etcd or mesh-failure
            # metric file is caught even if scale.py's own row were ever
            # wrong or absent.
            for signal_name, (metric_name, metric_label) in REQUIRED_SATURATION_SIGNALS.items():
                if signal_name == "latency_p99_ms":
                    # Already checked above as
                    # "upper_bound_kvstore_duration_perc99" for readability
                    # (kept in place to avoid changing an existing check
                    # name that dashboards/tests already key off of).
                    continue
                value = _find_rung_metric_value(role_dir, entries, suffix, metric_name, metric_label)
                ctx.add(
                    f"upper_bound_signal_present[{role}:{suffix}:{signal_name}]",
                    value is not None,
                    f"no parseable '{metric_name}' file with numeric {metric_label} for {suffix} "
                    f"(required verdict-driving signal {signal_name})",
                )


_SCENARIO_CHECKS = {
    "propagation-probe": lambda ctx, report_dir, succeeded_roles, args: _check_propagation_probe(
        ctx, report_dir, succeeded_roles, args.cluster_count,
        args.propagation_probe_count, args.propagation_peer_sample,
    ),
    "event-throughput": lambda ctx, report_dir, succeeded_roles, args: _check_event_throughput(
        ctx, report_dir, succeeded_roles,
    ),
    "pod-churn-combined": lambda ctx, report_dir, succeeded_roles, args: _check_pod_churn_combined(
        ctx, report_dir, succeeded_roles,
    ),
    "apiserver-failure": lambda ctx, report_dir, succeeded_roles, args: _check_apiserver_failure(
        ctx, report_dir, args.target_role,
    ),
    "policy-scale": lambda ctx, report_dir, succeeded_roles, args: _check_policy_scale(
        ctx, report_dir, succeeded_roles,
    ),
    "isolation": lambda ctx, report_dir, succeeded_roles, args: _check_isolation(
        ctx, report_dir, args.target_role,
    ),
    "node-churn-scale": lambda ctx, report_dir, succeeded_roles, args: _check_node_churn(
        ctx, report_dir, args.target_role, "node-churn-scale",
    ),
    "node-churn-replace": lambda ctx, report_dir, succeeded_roles, args: _check_node_churn(
        ctx, report_dir, args.target_role, "node-churn-replace",
    ),
    "node-churn-combined": lambda ctx, report_dir, succeeded_roles, args: _check_node_churn(
        ctx, report_dir, args.target_role, "node-churn-combined",
    ),
    "upper-bound": lambda ctx, report_dir, succeeded_roles, args: _check_upper_bound(
        ctx, report_dir, succeeded_roles, args.saturation_qps_list,
    ),
}


def evaluate(args: argparse.Namespace) -> Dict[str, Any]:
    """Run the common + scenario-specific contract and return the result dict."""
    ctx = EvidenceContext()
    succeeded_roles: List[str] = []
    failed_roles: List[str] = []

    # The worker-summary contract doesn't depend on report_dir, and every
    # scenario-specific check function tolerates a missing report_dir/role
    # dir on its own (returns a normal failing check rather than raising) —
    # so both run unconditionally. report_dir_exists is still recorded as
    # its own check purely for a clear, single-glance diagnostic.
    ctx.add("report_dir_exists", os.path.isdir(args.report_dir), f"{args.report_dir} is not a directory")
    succeeded_roles, failed_roles = _run_common_checks(
        ctx, args.worker_summary, args.cluster_count, args.report_dir,
    )

    handler = _SCENARIO_CHECKS.get(args.scenario)
    if handler is None:
        ctx.counts["contract"] = "common-only"
        ctx.add(
            "known_scenario_contract",
            False,
            f"no scenario-specific evidence contract is registered for {args.scenario!r}",
        )
    else:
        ctx.counts["contract"] = args.scenario
        handler(ctx, args.report_dir, succeeded_roles, args)

    ctx.counts["cluster_count"] = args.cluster_count
    ctx.counts["failed_roles"] = failed_roles

    return {
        "schema_version": SCHEMA_VERSION,
        "scenario": args.scenario,
        "known_scenario": handler is not None,
        "measurement_valid": ctx.valid,
        "checks": ctx.to_dict(),
        "reasons": ctx.reasons,
        "roles_checked": succeeded_roles,
        "counts": ctx.counts,
    }


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate post-execution, file-only scenario evidence for "
            "clustermesh-scale (does not query live cluster state)."
        ),
    )
    parser.add_argument("--scenario", required=True, help="Scenario name (e.g. pod-churn-combined).")
    parser.add_argument(
        "--report-dir", required=True,
        help="Base CL2 report directory for this scenario (contains one subdir per role).",
    )
    parser.add_argument("--worker-summary", required=True, help="Path to execute-parallel's worker-summary.json.")
    parser.add_argument("--cluster-count", required=True, type=int, help="Configured mesh cluster count.")
    parser.add_argument("--target-role", default="", help="Resolved target role, for target-scoped scenarios.")
    parser.add_argument(
        "--propagation-probe-count", type=int, default=0,
        help="Configured PROBE_COUNT for the propagation-probe scenario.",
    )
    parser.add_argument(
        "--propagation-peer-sample", type=int, default=0,
        help="Configured PEER_SAMPLE_MAX for the propagation-probe scenario (0 = unlimited).",
    )
    parser.add_argument(
        "--saturation-qps-list", default="",
        help="Comma-separated per-rung QPS list for the upper-bound scenario (rung count = list length).",
    )
    parser.add_argument("--output", required=True, help="Path to write the schema-versioned evidence JSON.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.cluster_count < 1:
        parser.error("--cluster-count must be >= 1")
    if args.propagation_probe_count < 0:
        parser.error("--propagation-probe-count must be >= 0")
    if args.propagation_peer_sample < 0:
        parser.error("--propagation-peer-sample must be >= 0")

    result = evaluate(args)
    try:
        _atomic_write_json(args.output, result)
    except OSError as error:
        print(f"scenario_evidence: could not write output {args.output}: {error}", file=sys.stderr)
        return 2

    return 0 if result["measurement_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
