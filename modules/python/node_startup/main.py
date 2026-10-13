"""Measure autoscaled node startup latency and write one JSON line per valid iteration.

Iterations are judged one by one (plan section 6a): a failed or invalid iteration
is dropped and the others are kept. With 1-4 valid iterations the ADO step is
marked SucceededWithIssues; with none, no file is written and the exit code is 1.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

from clients.kubernetes_client import KubernetesClient
from node_startup import probe, record
from node_startup.iteration import measure_iteration
from node_startup.timestamps import format_timestamp, parse_timestamp
from node_startup.validation import cni_readiness_signal, validate_iteration
from utils.logger_config import get_logger, setup_logging

logger = get_logger(__name__)

# Rough per-iteration cost when nothing goes wrong, used only to warn up front
# that the requested iterations probably won't fit before the deadline.
ESTIMATED_ITERATION_SECONDS = 180
DEFAULT_OPERATION_TIMEOUT_MINUTES = 15
SETTLE_TIMEOUT_SECONDS = 600


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return number


def non_negative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {value}")
    return number


def boolean(value):
    if value.lower() not in ("true", "false"):
        raise argparse.ArgumentTypeError(f"must be true or false, got {value}")
    return value.lower() == "true"


def name_equals_selector(value):
    name, separator, selector = value.partition("=")
    if not separator or not name or not selector:
        raise argparse.ArgumentTypeError(f"expected NAME=LABEL_SELECTOR, got {value}")
    return name, selector


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, help="Scenario name recorded in results, e.g. managed-cilium")
    parser.add_argument("--provisioner", required=True, help="Node provisioner recorded in results, e.g. cluster-autoscaler")
    parser.add_argument("--cluster-info-file", required=True, help="Output of `az aks show -o json`")
    parser.add_argument("--node-pool-name", required=True, help="Pool that must scale up for each probe")
    parser.add_argument("--node-label-key", required=True,
                        help="Node label identifying the pool: agentpool, or karpenter.sh/nodepool for Karpenter")
    parser.add_argument("--cni-daemonset-label", default=None,
                        help="Label selector of the CNI agent pods (e.g. k8s-app=cilium); omit if there is none")
    parser.add_argument("--cni-blocking-taint", default=None,
                        help="Taint key the CNI removes when ready (e.g. node.cilium.io/agent-not-ready)")
    parser.add_argument("--supplementary-cni-pod", action="append", type=name_equals_selector, default=[],
                        metavar="NAME=LABEL_SELECTOR",
                        help="Extra kube-system pod to time on the new node (informational); repeatable")
    parser.add_argument("--probe-namespace", required=True, help="Namespace for probe pods; created if missing")
    parser.add_argument("--iterations", required=True, type=positive_int)
    parser.add_argument("--iteration-cooldown-seconds", required=True, type=non_negative_int)
    parser.add_argument("--step-timeout-seconds", required=True, type=positive_int,
                        help="How long to wait for each probe pod to run")
    parser.add_argument("--deadline-epoch-seconds", required=True, type=int,
                        help="Don't start new iterations after this time, so upload and cleanup still fit")
    parser.add_argument("--uses-default-settings", required=True, type=boolean,
                        help="Whether iterations and cooldown equal the pipeline's checked-in defaults")
    parser.add_argument("--records-file", required=True, help="JSON Lines output, one record per valid iteration")
    return parser.parse_args(argv)


def utc_now_timestamp():
    return format_timestamp(datetime.now(timezone.utc))


def write_records_atomically(path, records):
    temporary_path = f"{path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        for item in records:
            file.write(json.dumps(item) + "\n")
    os.replace(temporary_path, path)


def run(args, k8s, clock=time.time, sleep=time.sleep):
    with open(args.cluster_info_file, encoding="utf-8") as file:
        cluster = record.cluster_info(json.load(file), args.node_pool_name)
    supplementary_cni_pods = dict(args.supplementary_cni_pod)
    # v1 semantics: whole minutes, 15 when the timeout is under a minute.
    operation_timeout_in_minutes = args.step_timeout_seconds // 60 or DEFAULT_OPERATION_TIMEOUT_MINUTES
    config = {
        "node_label_key": args.node_label_key,
        "node_pool_name": args.node_pool_name,
        "cni_daemonset_label": args.cni_daemonset_label,
        "cni_blocking_taint": args.cni_blocking_taint,
        "cni_readiness_signal": cni_readiness_signal(args.cni_daemonset_label),
        "supplementary_cni_pods": supplementary_cni_pods,
        "probe_image": probe.PROBE_IMAGE,
        "probe_namespace": args.probe_namespace,
        "step_timeout_seconds": args.step_timeout_seconds,
        "iteration_cooldown_seconds": args.iteration_cooldown_seconds,
        "uses_default_settings": args.uses_default_settings,
    }

    k8s.create_namespace(args.probe_namespace)

    estimated_seconds = args.iterations * (args.iteration_cooldown_seconds + ESTIMATED_ITERATION_SECONDS)
    if clock() + estimated_seconds > args.deadline_epoch_seconds:
        logger.warning("%d iterations need about %d minutes but the deadline is in %d minutes; "
                       "later iterations will probably be skipped",
                       args.iterations, estimated_seconds // 60, (args.deadline_epoch_seconds - clock()) // 60)

    valid = []
    dropped = []
    used_nodes = set()
    for iteration in range(1, args.iterations + 1):
        if clock() >= args.deadline_epoch_seconds:
            for skipped in range(iteration, args.iterations + 1):
                dropped.append((skipped, "skipped: deadline passed"))
            logger.warning("Deadline passed; skipping iterations %d-%d", iteration, args.iterations)
            break

        logger.info("Starting iteration %d/%d", iteration, args.iterations)
        start_timestamp = utc_now_timestamp()
        try:
            result = measure_iteration(
                k8s,
                node_pool_name=args.node_pool_name,
                node_label_key=args.node_label_key,
                namespace=args.probe_namespace,
                pod_name=f"latency-probe-{iteration}",
                operation_timeout_in_minutes=operation_timeout_in_minutes,
                cni_daemonset_label=args.cni_daemonset_label,
                cni_blocking_taint=args.cni_blocking_taint,
                supplementary_cni_pods=supplementary_cni_pods,
            )
        except Exception as e:
            logger.error("FAILED NODE STARTUP ITERATION %d: %s", iteration, e)
            dropped.append((iteration, f"failed: {e}"))
            remaining_seconds = args.deadline_epoch_seconds - clock()
            if not probe.is_karpenter(args.node_label_key) and iteration < args.iterations and remaining_seconds > 0:
                try:
                    probe.wait_for_pool_settled(k8s, args.node_label_key, args.node_pool_name,
                                                timeout_seconds=min(SETTLE_TIMEOUT_SECONDS, remaining_seconds))
                except Exception as settle_error:
                    logger.warning("Pool settle wait failed; continuing: %s", settle_error)
        else:
            end_timestamp = utc_now_timestamp()
            problems = validate_iteration(result, used_nodes, args.cni_daemonset_label, args.cni_blocking_taint)
            if problems:
                logger.error("FAILED NODE STARTUP VALIDATION %d: %s; measurement: %s",
                             iteration, "; ".join(problems), json.dumps(result["measurement"]))
                dropped.append((iteration, "invalid: " + "; ".join(problems)))
            else:
                used_nodes.add(result["measurement"]["node_name"])
                valid.append((iteration, result, start_timestamp, end_timestamp))

        if iteration < args.iterations:
            # A cooldown ending past the deadline only delays upload and cleanup.
            if clock() + args.iteration_cooldown_seconds >= args.deadline_epoch_seconds:
                for skipped in range(iteration + 1, args.iterations + 1):
                    dropped.append((skipped, "skipped: deadline passed"))
                logger.warning("Deadline reached; skipping iterations %d-%d", iteration + 1, args.iterations)
                break
            if args.iteration_cooldown_seconds > 0:
                logger.info("Waiting %d seconds before the next iteration", args.iteration_cooldown_seconds)
                sleep(args.iteration_cooldown_seconds)

    if not valid:
        logger.error("No valid iterations out of %d: %s", args.iterations, dropped)
        return 1

    records = []
    for iteration, result, start_timestamp, end_timestamp in valid:
        measurement = dict(result["measurement"])
        # v1 stored these inside the measurement too; kept for key parity.
        measurement["iteration"] = iteration
        measurement["total_iterations"] = args.iterations
        duration = (parse_timestamp(end_timestamp) - parse_timestamp(start_timestamp)).total_seconds()
        records.append(record.build_record(
            scenario=args.scenario,
            provisioner=args.provisioner,
            iteration=iteration,
            total_iterations=args.iterations,
            valid_iterations=len(valid),
            operation=record.operation_info(start_timestamp, end_timestamp, duration),
            cluster=cluster,
            config=config,
            environment=result["environment"],
            measurement=measurement,
        ))
    write_records_atomically(args.records_file, records)
    logger.info("Wrote %d of %d iterations to %s", len(valid), args.iterations, args.records_file)

    if dropped:
        summary = "; ".join(f"iteration {iteration} {reason}" for iteration, reason in dropped)
        print(f"##vso[task.logissue type=warning]Dropped {len(dropped)} of {args.iterations} iterations: {summary}")
        print("##vso[task.complete result=SucceededWithIssues;]")
    return 0


def main(argv=None):
    setup_logging()
    args = parse_args(argv)
    return run(args, KubernetesClient())


if __name__ == "__main__":
    sys.exit(main())
