"""Evaluate per-scenario hard-worker continuation policy."""

import argparse
import json
import os
import sys


FAILURE_RATES = {
    "propagation-probe": 0,
    "event-throughput": 3,
    "pod-churn-combined": 3,
    "apiserver-failure": 3,
    "policy-scale": 3,
    "isolation": 3,
    "node-churn-scale": 3,
    "node-churn-replace": 3,
    "node-churn-combined": 3,
    "upper-bound": 10,
}

TARGET_REQUIRED_SCENARIOS = {
    "apiserver-failure",
    "isolation",
    "node-churn-scale",
    "node-churn-replace",
    "node-churn-combined",
}


def _compute_overall_failure(measurement_valid, suite_continue):
    """Combine this scenario's own validity with the suite-wide decision.

    A scenario is a failure (from the build's point of view) if ITS OWN
    measurement was invalid, OR if the suite cannot safely continue past
    it. `suite_continue` is None until the post-scenario recovery signals
    (health gate, artifact preservation, mock reconcile) are known -- in
    that case only this scenario's own measurement validity is decisive.
    """
    if not measurement_valid:
        return True
    if suite_continue is None:
        return False
    return not suite_continue


def evaluate_policy(
    scenario,
    cluster_count,
    worker_summary,
    target_role="",
    non_worker_failure=False,
    target_stimulus_valid=True,
    evidence_valid=True,
    recovery_valid=None,
    infrastructure_healthy=None,
    artifact_preserved=None,
    mock_reconcile_valid=None,
):
    """Return a JSON-serializable continuation decision.

    `evidence_valid` folds into THIS scenario's own measurement validity
    (`measurement_valid`) -- a scenario whose file-only evidence contract
    failed did not actually measure what it claims to, regardless of how
    many CL2 workers reported success.

    `recovery_valid`, `infrastructure_healthy`, `artifact_preserved`, and
    `mock_reconcile_valid` are the shared-infrastructure recovery signals
    that only exist AFTER this scenario's post-scenario cleanup has run.
    Callers evaluating BEFORE cleanup (to record a scenario's own
    measurement outcome as soon as it is known) leave these None; callers
    evaluating AFTER cleanup pass explicit booleans, at which point
    `suite_continue` becomes decidable. `suite_continue` is deliberately
    independent of `measurement_valid` -- an invalid MEASUREMENT (e.g. a
    worker loss above tolerance, a target stimulus timeout, bad evidence) does
    not by itself mean the shared clusters are unsafe for the NEXT
    scenario; only a failed recovery/health-gate/artifact/mock-reconcile
    signal does.
    """
    failure_rate = FAILURE_RATES.get(scenario, 0)
    allowed_failures = cluster_count * failure_rate // 100
    failed_roles = sorted(worker_summary.get("failed_roles") or [])
    failed_count = worker_summary.get("failed_count")
    total_workers = worker_summary.get("total_workers")
    measurement_reasons = []

    if not isinstance(failed_count, int) or failed_count < 0:
        measurement_reasons.append("worker summary has invalid failed_count")
        failed_count = cluster_count
    if not isinstance(total_workers, int) or total_workers != cluster_count:
        measurement_reasons.append(
            f"worker summary total_workers={total_workers!r}, expected={cluster_count}"
        )
    if failed_count != len(failed_roles):
        measurement_reasons.append(
            "worker summary failed_count does not match failed_roles length"
        )
    if failed_count > allowed_failures:
        measurement_reasons.append(
            f"worker failures {failed_count} exceed allowed {allowed_failures}"
        )
    if non_worker_failure:
        measurement_reasons.append("host-side stimulus or probe failed")
    if not target_stimulus_valid:
        measurement_reasons.append("required target stimulus/recovery was not verified")
    if not evidence_valid:
        measurement_reasons.append("scenario evidence validation failed")

    target_required = scenario in TARGET_REQUIRED_SCENARIOS
    if target_required:
        if not target_role:
            measurement_reasons.append("required target role could not be resolved")
        elif target_role in failed_roles:
            measurement_reasons.append(f"required target worker failed: {target_role}")

    measurement_valid = not measurement_reasons

    suite_stop_reasons = []
    if recovery_valid is False:
        suite_stop_reasons.append(
            "post-scenario recovery/cleanup was not verified"
        )
    if infrastructure_healthy is False:
        suite_stop_reasons.append(
            "shared infrastructure health gate did not pass"
        )
    if artifact_preserved is False:
        suite_stop_reasons.append(
            "scenario artifact preservation failed"
        )
    if mock_reconcile_valid is False:
        suite_stop_reasons.append(
            "mock layer reconciliation failed"
        )

    lifecycle_signals = (
        recovery_valid,
        infrastructure_healthy,
        artifact_preserved,
        mock_reconcile_valid,
    )
    if any(signal is None for signal in lifecycle_signals):
        suite_continue = None
    else:
        suite_continue = all(lifecycle_signals)

    overall_failure = _compute_overall_failure(measurement_valid, suite_continue)

    return {
        "schema_version": 1,
        "scenario": scenario,
        "cluster_count": cluster_count,
        "worker_failure_rate_percent": failure_rate,
        "worker_allowed_failures": allowed_failures,
        "worker_failed_count": failed_count,
        "failed_roles": failed_roles,
        "target_required": target_required,
        "target_role": target_role or None,
        "target_stimulus_valid": target_stimulus_valid,
        "non_worker_failure": non_worker_failure,
        "evidence_valid": evidence_valid,
        "tolerated_worker_failures": measurement_valid and failed_count > 0,
        "measurement_valid": measurement_valid,
        "measurement_reasons": measurement_reasons,
        "recovery_valid": recovery_valid,
        "infrastructure_healthy": infrastructure_healthy,
        "artifact_preserved": artifact_preserved,
        "mock_reconcile_valid": mock_reconcile_valid,
        "suite_continue": suite_continue,
        "suite_stop_reasons": suite_stop_reasons,
        "overall_failure": overall_failure,
        # Backwards-compatible aliases: pre-existing callers/dashboards
        # read `success`/`reasons` as THIS scenario's own measurement
        # validity, never the suite-wide continuation decision.
        "success": measurement_valid,
        "reasons": measurement_reasons,
    }


def _parse_bool(value):
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {value!r}")


def _parse_optional_bool(value):
    if value == "":
        return None
    return _parse_bool(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--cluster-count", required=True, type=int)
    parser.add_argument("--worker-summary", required=True)
    parser.add_argument("--target-role", default="")
    parser.add_argument("--non-worker-failure", type=_parse_bool, default=False)
    parser.add_argument("--target-stimulus-valid", type=_parse_bool, default=True)
    parser.add_argument("--evidence-valid", type=_parse_bool, default=True)
    parser.add_argument(
        "--recovery-valid", type=_parse_optional_bool, default=None,
        help="Post-scenario recovery/cleanup verification result. Omit "
             "(or pass '') for an initial, pre-cleanup evaluation.",
    )
    parser.add_argument(
        "--infrastructure-healthy", type=_parse_optional_bool, default=None,
        help="Shared-infrastructure health gate result. Omit (or pass '') "
             "for an initial, pre-cleanup evaluation.",
    )
    parser.add_argument(
        "--artifact-preserved", type=_parse_optional_bool, default=None,
        help="Scenario artifact preservation result. Omit (or pass '') "
             "for an initial, pre-cleanup evaluation.",
    )
    parser.add_argument(
        "--mock-reconcile-valid", type=_parse_optional_bool, default=None,
        help="Mock-layer reconciliation result. Omit (or pass '') for an "
             "initial, pre-cleanup evaluation.",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        with open(args.worker_summary, "r", encoding="utf-8") as handle:
            worker_summary = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        worker_summary = {}
        load_error = str(error)
    else:
        load_error = ""

    decision = evaluate_policy(
        scenario=args.scenario,
        cluster_count=args.cluster_count,
        worker_summary=worker_summary,
        target_role=args.target_role,
        non_worker_failure=args.non_worker_failure,
        target_stimulus_valid=args.target_stimulus_valid,
        evidence_valid=args.evidence_valid,
        recovery_valid=args.recovery_valid,
        infrastructure_healthy=args.infrastructure_healthy,
        artifact_preserved=args.artifact_preserved,
        mock_reconcile_valid=args.mock_reconcile_valid,
    )
    if load_error:
        reason = f"worker summary could not be loaded: {load_error}"
        decision["measurement_valid"] = False
        decision["measurement_reasons"].append(reason)
        decision["overall_failure"] = _compute_overall_failure(
            decision["measurement_valid"], decision["suite_continue"]
        )
        # Keep the backwards-compatible aliases in sync.
        decision["success"] = decision["measurement_valid"]
        decision["reasons"] = decision["measurement_reasons"]

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    temporary = f"{args.output}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(decision, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, args.output)
    return 0 if decision["measurement_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
