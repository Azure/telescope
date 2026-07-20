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


def evaluate_policy(
    scenario,
    cluster_count,
    worker_summary,
    target_role="",
    non_worker_failure=False,
    target_stimulus_valid=True,
):
    """Return a JSON-serializable continuation decision."""
    failure_rate = FAILURE_RATES.get(scenario, 0)
    allowed_failures = cluster_count * failure_rate // 100
    failed_roles = sorted(worker_summary.get("failed_roles") or [])
    failed_count = worker_summary.get("failed_count")
    total_workers = worker_summary.get("total_workers")
    reasons = []

    if not isinstance(failed_count, int) or failed_count < 0:
        reasons.append("worker summary has invalid failed_count")
        failed_count = cluster_count
    if not isinstance(total_workers, int) or total_workers != cluster_count:
        reasons.append(
            f"worker summary total_workers={total_workers!r}, expected={cluster_count}"
        )
    if failed_count != len(failed_roles):
        reasons.append(
            "worker summary failed_count does not match failed_roles length"
        )
    if failed_count > allowed_failures:
        reasons.append(
            f"worker failures {failed_count} exceed allowed {allowed_failures}"
        )
    if non_worker_failure:
        reasons.append("host-side stimulus or probe failed")
    if not target_stimulus_valid:
        reasons.append("required target stimulus/recovery was not verified")

    target_required = scenario in TARGET_REQUIRED_SCENARIOS
    if target_required:
        if not target_role:
            reasons.append("required target role could not be resolved")
        elif target_role in failed_roles:
            reasons.append(f"required target worker failed: {target_role}")

    success = not reasons
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
        "tolerated_worker_failures": success and failed_count > 0,
        "success": success,
        "reasons": reasons,
    }


def _parse_bool(value):
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {value!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--cluster-count", required=True, type=int)
    parser.add_argument("--worker-summary", required=True)
    parser.add_argument("--target-role", default="")
    parser.add_argument("--non-worker-failure", type=_parse_bool, default=False)
    parser.add_argument("--target-stimulus-valid", type=_parse_bool, default=True)
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
    )
    if load_error:
        decision["success"] = False
        decision["reasons"].append(
            f"worker summary could not be loaded: {load_error}"
        )

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    temporary = f"{args.output}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(decision, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, args.output)
    return 0 if decision["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
