"""
ClusterMesh scale-test harness.

Per-cluster execute (`scale.py execute`) is single-cluster: it spawns one
ClusterLoader2 docker container against one kubeconfig. The Telescope pipeline
fans out across N clusters; each per-cluster invocation emits one JSONL with a
`cluster` attribution column so concatenated results from N clusters are
queryable per-cluster downstream.

Multi-cluster fan-out (`scale.py execute-parallel`, Phase 3) bounds parallel
CL2 invocations across the mesh — see `execute_parallel` below for the worker
model. Each parallel worker shells out to `run-cl2-on-cluster.sh` so the
existing per-iteration bash semantics (CL2 run + junit gate + log capture +
failure diag) are preserved exactly per cluster.

Phase 1 is intentionally trivial: deploy a small fixed number of pods, no churn,
no fortio, no network policies. The goal of Phase 1 is to prove the multi-cluster
harness + topology + aggregation works end-to-end. Real measurements
(cross-cluster event throughput, identity propagation, etc.) come in plan.md
Phase 2 by adding measurement modules to config/modules/measurements/ and new
parameters to configure/collect.
"""
import argparse
import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone

from clusterloader2.utils import parse_xml_to_json, run_cl2_command, process_cl2_reports


# Phase 4b — Scenario #6 (Upper Bound / Saturation) classifier constants.
# Versioned so downstream Kusto dashboards can compare verdicts across
# tuning iterations. Raw signal values + thresholds are emitted alongside
# the verdict so dashboards can recompute verdicts post-hoc without re-
# running the test if thresholds need calibration.
#
# Thresholds rationale (v1 — first-smoke calibration; revisit after first
# n=2 green):
#   latency_p99_ms          — 500ms p99 of cilium_kvstoremesh_kvstore_
#                             operations_duration. Healthy AKS-managed
#                             Cilium runs show p99 < 100ms; 5× that is
#                             the saturation knee.
#   queue_size_perc99       — 1000 in cilium_kvstoremesh_kvstore_sync_
#                             queue_size. Steady-state on green pod-churn
#                             runs is single digits; 3 orders of magnitude
#                             above noise floor is unambiguously bad.
#   apiserver_max_cpu_cores — 1.5 cores per clustermesh-apiserver pod
#                             (ClusterMeshApiserverPodCPU PerPodMax).
#                             AKS-managed Cilium typically requests
#                             0.5-1.0 vCPU; saturated >2× allocation = at
#                             risk of throttling.
#   mesh_failure_rate_max   — 0.5 reconnect-failures/s. Plan.md deferred
#                             decision #6 documents the green-run
#                             baseline of 4-6 reconnects per 36 min run
#                             ≈ 0.003/s (uniformly distributed across
#                             peers, benign Fleet churn). 0.5/s = ~150×
#                             that baseline → real failure burst.
#   etcd_commit_p99_ms      — 200ms p99 of etcd_debugging_disk_backend_
#                             commit_write_duration. Etcd's design target
#                             is single-digit ms; 200ms = backed-up disk
#                             subsystem.
SATURATION_CLASSIFIER_VERSION = "saturation-v1"
SATURATION_THRESHOLDS = {
    "latency_p99_ms": 500.0,
    "queue_size_perc99": 1000.0,
    "apiserver_max_cpu_cores": 1.5,
    "mesh_failure_rate_max": 0.5,
    "etcd_commit_p99_ms": 200.0,
}


def configure_clusterloader2(
    namespaces,
    deployments_per_namespace,
    replicas_per_deployment,
    operation_timeout,
    override_file,
    churn_cycles=5,
    churn_up_duration="60s",
    churn_down_duration="60s",
    kill_duration="10m",
    kill_interval_seconds=10,
    kill_batch=5,
    kill_duration_seconds=600,
    kill_job_deadline_seconds=660,
    apiserver_kill_target_context="clustermesh-1",
    apiserver_kill_recovery_timeout_seconds=240,
    apiserver_kill_observation_seconds=60,
    ha_config_replicas=3,
    node_churn_target_context="clustermesh-1",
    node_churn_cycles=3,
    node_churn_delta=5,
    node_churn_settle_seconds=60,
    node_churn_scale_duration_seconds=1800,
    node_churn_replace_duration_seconds=1500,
    node_churn_combined_duration_seconds=3300,
    node_replace_batch_size=10,
    node_churn_ready_timeout_seconds=300,
    saturation_qps_list="100,500,1500,4000,10000",
    saturation_restarts_list="2,4,8,15,25",
    saturation_rung_duration_seconds=240,
    saturation_settle_seconds=90,
):
    with open(override_file, "w", encoding="utf-8") as f:
        # Prometheus stack — keep the Cilium-scrape flags ON so the
        # cilium/control-plane/clustermesh measurement modules have data to
        # query. The base memory REQUEST is set via the --prometheus-memory-request
        # CLI flag in execute_clusterloader2 (the CL2_PROMETHEUS_MEMORY_REQUEST
        # overrides key is not honored by this CL2 image). Memory LIMIT below
        # IS honored as an overrides key and must be >= the request to satisfy
        # k8s admission.
        f.write("CL2_PROMETHEUS_TOLERATE_MASTER: true\n")
        # Prometheus memory limit. Bumped 2Gi\u21924Gi 2026-05-15 after build
        # 67224 showed prometheus-k8s-0 in CrashLoopBackOff on saturation
        # runs. Then bumped 4Gi\u219212Gi 2026-05-15 after build 67279
        # showed Prom STILL OOM'ing at Rung 2 even with 4Gi when the
        # restart-burst workload pushed too many series/samples.
        # D8ds_v4 prompool has 32GB RAM so 12Gi is safe with headroom.
        # CL2_PROMETHEUS_MEMORY_LIMIT is honored as a CL2 overrides key
        # (unlike the *_FACTOR knobs which are silently broken — see
        # plan.md "What we built" item 16).
        f.write("CL2_PROMETHEUS_MEMORY_LIMIT: 12Gi\n")
        # Pin Prometheus to the dedicated `prompool` node (label
        # prometheus=true is set in azure-2.tfvars extra_node_pool). Without
        # this, prometheus-k8s lands on the default workload pool and
        # competes with the 200 event-throughput pods for CPU/memory,
        # causing per-node overcommit and Pending workload pods.
        f.write('CL2_PROMETHEUS_NODE_SELECTOR: "prometheus: \\"true\\""\n')
        f.write("CL2_PROMETHEUS_SCRAPE_CILIUM_AGENT: true\n")
        f.write("CL2_PROMETHEUS_SCRAPE_CILIUM_OPERATOR: true\n")
        f.write("CL2_POD_STARTUP_LATENCY_THRESHOLD: 3m\n")
        # APIResponsivenessPrometheus default SLO (perc99 ≤ 1s) is tuned for
        # production-scale clusters in steady state; on Phase-1 dev clusters
        # the kube-apiserver hits multi-second perc99 during the Prometheus
        # stack bring-up (mutatingwebhookconfigurations APPLY,
        # customresourcedefinitions POST/PUT). The metric is still recorded
        # — we just stop CL2 from failing the test on threshold breaches.
        f.write("CL2_ENABLE_VIOLATIONS_FOR_API_CALL_PROMETHEUS_SIMPLE: false\n")

        # Topology knobs — trivial defaults for Phase 1 vertical slice.
        f.write(f"CL2_NAMESPACES: {namespaces}\n")
        f.write(f"CL2_DEPLOYMENTS_PER_NAMESPACE: {deployments_per_namespace}\n")
        f.write(f"CL2_REPLICAS_PER_DEPLOYMENT: {replicas_per_deployment}\n")
        f.write(f"CL2_OPERATION_TIMEOUT: {operation_timeout}\n")

        # Phase 4a — Scenario #2 (Pod Churn Stress) knobs.
        # Written unconditionally with defaults so an event-throughput run
        # (which doesn't reference these CL2_* params in its template)
        # silently ignores them. CL2 does not fail on unknown overrides
        # keys, so the cost is a few lines of YAML noise per non-churn run.
        # The alternative — splitting configure into per-scenario
        # subcommands — would proliferate harness surface area; see
        # plan.md Phase 4a notes.
        f.write(f"CL2_CHURN_CYCLES: {churn_cycles}\n")
        f.write(f"CL2_CHURN_UP_DURATION: {churn_up_duration}\n")
        f.write(f"CL2_CHURN_DOWN_DURATION: {churn_down_duration}\n")
        f.write(f"CL2_KILL_DURATION: {kill_duration}\n")
        f.write(f"CL2_KILL_INTERVAL_SECONDS: {kill_interval_seconds}\n")
        f.write(f"CL2_KILL_BATCH: {kill_batch}\n")
        f.write(f"CL2_KILL_DURATION_SECONDS: {kill_duration_seconds}\n")
        f.write(f"CL2_KILL_JOB_DEADLINE_SECONDS: {kill_job_deadline_seconds}\n")

        # Phase 4b — Scenario #4 (ClusterMesh APIServer Failure) knobs.
        # Same unconditional-write pattern as the pod-churn knobs above:
        # CL2 templates that don't reference these silently ignore. Allows
        # share-infra runs where multiple scenarios share one overrides.yaml.
        f.write(f"CL2_APISERVER_KILL_TARGET_CONTEXT: {apiserver_kill_target_context}\n")
        f.write(f"CL2_APISERVER_KILL_RECOVERY_TIMEOUT_SECONDS: {apiserver_kill_recovery_timeout_seconds}\n")
        f.write(f"CL2_APISERVER_KILL_OBSERVATION_SECONDS: {apiserver_kill_observation_seconds}\n")

        # Phase 4b — Scenario #7 (HA Configuration Validation) knob.
        # Single replicas-count override consumed by ha-config.yaml. Other
        # scenarios' CL2 configs don't reference it; ignored silently.
        f.write(f"CL2_HA_CONFIG_REPLICAS: {ha_config_replicas}\n")

        # Phase 4b — Scenario #3 (Node Churn / IP Churn) knobs.
        # node-churn-{scale,replace,combined}.yaml each consume a subset.
        # node-churner.sh (driven from execute.yml, NOT Method:Exec — CL2
        # image has no az CLI) reads the same matrix vars directly; these
        # overrides drive the CL2-side sleep/sentinel window that aligns
        # with the churner's wall-clock run.
        f.write(f"CL2_NODE_CHURN_TARGET_CONTEXT: {node_churn_target_context}\n")
        f.write(f"CL2_NODE_CHURN_CYCLES: {node_churn_cycles}\n")
        f.write(f"CL2_NODE_CHURN_DELTA: {node_churn_delta}\n")
        f.write(f"CL2_NODE_CHURN_SETTLE_SECONDS: {node_churn_settle_seconds}\n")
        f.write(f"CL2_NODE_CHURN_SCALE_DURATION_SECONDS: {node_churn_scale_duration_seconds}\n")
        f.write(f"CL2_NODE_CHURN_REPLACE_DURATION_SECONDS: {node_churn_replace_duration_seconds}\n")
        f.write(f"CL2_NODE_CHURN_COMBINED_DURATION_SECONDS: {node_churn_combined_duration_seconds}\n")
        f.write(f"CL2_NODE_REPLACE_BATCH_SIZE: {node_replace_batch_size}\n")
        f.write(f"CL2_NODE_CHURN_READY_TIMEOUT_SECONDS: {node_churn_ready_timeout_seconds}\n")

        # Phase 4b — Scenario #6 (Upper Bound / Saturation) knobs.
        # upper-bound.yaml CL2 config consumes these to drive the per-rung
        # QPS ramp + restart amplitude. Written unconditionally with the
        # same defaulted-pattern as scenario #2-#5 knobs: non-saturation
        # CL2 configs simply ignore them (CL2 doesn't fail on unknown
        # overrides keys). The qps and restarts lists are written as
        # comma-separated strings; upper-bound.yaml uses CL2's
        # StringSplit template func to parse.
        f.write(f"CL2_SATURATION_QPS_LIST: \"{saturation_qps_list}\"\n")
        f.write(f"CL2_SATURATION_RESTARTS_LIST: \"{saturation_restarts_list}\"\n")
        f.write(f"CL2_SATURATION_RUNG_DURATION_SECONDS: {saturation_rung_duration_seconds}\n")
        f.write(f"CL2_SATURATION_SETTLE_SECONDS: {saturation_settle_seconds}\n")

    with open(override_file, "r", encoding="utf-8") as f:
        print(f"Content of file {override_file}:\n{f.read()}")


def execute_clusterloader2(
    cl2_image,
    cl2_config_dir,
    cl2_report_dir,
    cl2_config_file,
    kubeconfig,
    provider,
    tear_down_prometheus=False,
):
    run_cl2_command(
        kubeconfig,
        cl2_image,
        cl2_config_dir,
        cl2_report_dir,
        provider,
        cl2_config_file=cl2_config_file,
        overrides=True,
        enable_prometheus=True,
        # Default False preserves the diagnostic-on-failure capability — when
        # CL2 fails, run-cl2-on-cluster.sh's FAILURE DIAG block can dump
        # prometheus-operator + prometheus-k8s pod logs. Set True in
        # share-infra mode (multi-scenario per lifecycle) so each scenario's
        # CL2 invocation gets a clean Prometheus deploy and the previous
        # scenario's PodMonitor/scrape config doesn't bleed in.
        tear_down_prometheus=tear_down_prometheus,
        scrape_kubelets=True,
        scrape_ksm=True,
        scrape_metrics_server=True,
        # CL2 default is 10Gi which doesn't fit a Standard_D4s_v4 / 16GB node
        # after k8s + Cilium overhead. Override via the CLI flag rather than
        # `CL2_PROMETHEUS_MEMORY_REQUEST` overrides.yaml key — that key is not
        # honored by this CL2 image (verified via prometheus-operator log
        # showing PrometheusMemoryRequest:10Gi at runtime). Pair this with
        # CL2_PROMETHEUS_MEMORY_LIMIT in the overrides file so request <= limit.
        prometheus_memory_request="1Gi",
    )


# Module-level lock + Popen tracking for execute_parallel. Lock keeps log lines
# atomic across worker threads; the Popen list lets a SIGINT/SIGTERM handler
# terminate live children on cancel (AzDO step cancel, Ctrl-C in dev).
_PARALLEL_STDOUT_LOCK = threading.Lock()
_PARALLEL_LIVE_POPENS = []
_PARALLEL_LIVE_POPENS_LOCK = threading.Lock()


def _emit_prefixed_line(role, line):
    # AzDO recognizes ##vso[...] service messages only when they appear at
    # column 0 — prefixing them would drop the structured annotation. Emit
    # those unprefixed; everything else gets the [role] tag for readability
    # under interleaved output.
    if line.startswith("##"):
        out = line
    else:
        out = f"[{role}] {line}"
    with _PARALLEL_STDOUT_LOCK:
        sys.stdout.write(out)
        sys.stdout.flush()


def _run_one_cluster(role, worker_script, worker_args, env=None):
    """Spawn the per-cluster worker script and stream its merged stdout/stderr.

    Returns (role, exit_code). Exit code is the worker script's exit (which
    is the authoritative pass/fail per cluster — the script does its own
    junit gate + log capture + failure diag).
    """
    cmd = ["bash", worker_script, role, *worker_args]
    # bufsize=1 + text=True gives us line-buffered text reads so the prefix
    # writer sees one CL2 log line at a time. PYTHONUNBUFFERED ensures the
    # nested python3 scale.py execute child also flushes per-line.
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    child_env.setdefault("PYTHONUNBUFFERED", "1")
    # Not using `with subprocess.Popen(...)` because the Popen handle is
    # registered in _PARALLEL_LIVE_POPENS for the SIGINT/SIGTERM handler;
    # `with` would close stdout at function exit and cancel signal-based
    # termination semantics. The try/finally below handles cleanup.
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
        env=child_env,
    )
    with _PARALLEL_LIVE_POPENS_LOCK:
        _PARALLEL_LIVE_POPENS.append(proc)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            _emit_prefixed_line(role, line)
        proc.wait()
    finally:
        with _PARALLEL_LIVE_POPENS_LOCK:
            try:
                _PARALLEL_LIVE_POPENS.remove(proc)
            except ValueError:
                pass
    return role, proc.returncode


def _install_parallel_signal_handlers():
    """Terminate live worker subprocesses on SIGINT/SIGTERM.

    AzDO step cancel sends SIGTERM. ThreadPoolExecutor will not reap child
    processes spawned by its workers, and each worker bash script in turn
    spawns `python3 scale.py execute` which spawns a docker container — so
    abrupt parent death without explicit teardown can leave orphan docker
    containers running. We best-effort terminate the bash workers; the docker
    container behind them will exit when its parent python child exits.
    """
    def _terminate_all(signum, _frame):
        with _PARALLEL_STDOUT_LOCK:
            sys.stdout.write(
                f"[execute-parallel] received signal {signum}, "
                "terminating live workers\n"
            )
            sys.stdout.flush()
        with _PARALLEL_LIVE_POPENS_LOCK:
            for proc in list(_PARALLEL_LIVE_POPENS):
                try:
                    proc.terminate()
                except Exception:  # pylint: disable=broad-except
                    pass
        # Re-raise default behavior for the original signal so the parent
        # exits with the conventional code (128+signum). This also unblocks
        # any executor.shutdown(wait=True) waiters.
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGINT, _terminate_all)
    signal.signal(signal.SIGTERM, _terminate_all)


def execute_parallel(
    clusters_file,
    max_concurrent,
    worker_script,
    cl2_image,
    cl2_config_dir,
    cl2_config_file,
    cl2_report_dir_base,
    provider,
    python_script_file,
    python_workdir,
    tear_down_prometheus=False,
):
    """Fan out CL2 across N clusters with bounded concurrency.

    Each cluster's CL2 + log capture + failure diag runs in its own bash
    worker process (run-cl2-on-cluster.sh). At most `max_concurrent` run
    in parallel. Per-cluster log capture happens IMMEDIATELY when that
    cluster's CL2 finishes — before peer clusters complete — so kubectl
    --tail windows and `kubectl get events` recency don't age out.

    The worker script's exit code is the authoritative per-cluster
    pass/fail (it does its own junit gate). This function aggregates:
    returns 0 iff every worker exited 0; otherwise 1. Matches the
    sequential `if failures > 0; exit 1` semantics that execute.yml had
    before parallelization, so the AzDO step's pass/fail signal is
    unchanged from the user's perspective.

    `clusters_file` schema: a JSON array of objects with at least `role`
    and `kubeconfig` fields. Extra fields (e.g. `name`, `rg`) are ignored
    so the same JSON file produced by execute.yml's discovery step (which
    also feeds collect.yml) can be reused without a separate write.

    Known concurrency risk: `run_cl2_command` mounts `~/.azure` rw into
    every CL2 docker container (utils.py:69-70). At max_concurrent > 1
    those containers concurrently read/write the MSAL token cache. If
    this causes auth flakes on real 5/10/20-cluster runs, isolate per
    worker (TODO Phase 3 follow-up).
    """
    with open(clusters_file, "r", encoding="utf-8") as f:
        clusters = json.load(f)
    if not isinstance(clusters, list) or not clusters:
        raise ValueError(
            f"clusters file {clusters_file} must be a non-empty JSON array"
        )

    # Validate up front so we fail fast before spawning anything.
    for idx, c in enumerate(clusters):
        if "role" not in c or "kubeconfig" not in c:
            raise ValueError(
                f"clusters[{idx}] missing 'role' or 'kubeconfig': {c}"
            )

    if max_concurrent < 1:
        raise ValueError(f"max_concurrent must be >= 1, got {max_concurrent}")

    _install_parallel_signal_handlers()

    print(
        f"[execute-parallel] dispatching {len(clusters)} cluster(s) "
        f"with max_concurrent={max_concurrent}",
        flush=True,
    )

    results = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_concurrent
    ) as executor:
        futures = {}
        for c in clusters:
            role = c["role"]
            kubeconfig = c["kubeconfig"]
            report_dir = os.path.join(cl2_report_dir_base, role)
            worker_args = [
                kubeconfig,
                report_dir,
                cl2_image,
                cl2_config_dir,
                cl2_config_file,
                provider,
                python_script_file,
                python_workdir,
                # Last positional: 1 = tear down Prometheus at end of CL2 (used
                # by share-infra mode so the next scenario's CL2 deploys a
                # fresh Prom); 0 = preserve Prom for failure-diagnostic dump.
                "1" if tear_down_prometheus else "0",
            ]
            fut = executor.submit(
                _run_one_cluster, role, worker_script, worker_args
            )
            futures[fut] = role

        for fut in concurrent.futures.as_completed(futures):
            role = futures[fut]
            try:
                _, exit_code = fut.result()
            except Exception as e:  # pylint: disable=broad-except
                # Worker raised before producing an exit code (e.g. could not
                # spawn bash). Treat as a failure for that cluster — surface
                # the error and continue collecting peers.
                print(
                    f"[execute-parallel] {role}: worker raised: {e}",
                    flush=True,
                )
                results.append((role, 1))
            else:
                results.append((role, exit_code))

    failed = [r for r, code in results if code != 0]
    succeeded = [r for r, code in results if code == 0]
    print(
        f"[execute-parallel] summary: {len(succeeded)} succeeded, "
        f"{len(failed)} failed (max_concurrent={max_concurrent})",
        flush=True,
    )
    if failed:
        print(
            f"[execute-parallel] failed clusters: {', '.join(sorted(failed))}",
            flush=True,
        )
        return 1
    return 0


def collect_clusterloader2(
    cl2_report_dir,
    cloud_info,
    run_id,
    run_url,
    result_file,
    test_type,
    start_timestamp,
    cluster_name,
    cluster_count,
    mesh_size,
    namespaces,
    deployments_per_namespace,
    replicas_per_deployment,
    trigger_reason="",
    churn_cycles=0,
    churn_up_duration="",
    churn_down_duration="",
    kill_duration_seconds=0,
    kill_interval_seconds=0,
    kill_batch=0,
    saturation_qps_list="",
    saturation_restarts_list="",
):
    details = parse_xml_to_json(os.path.join(cl2_report_dir, "junit.xml"), indent=2)
    json_data = json.loads(details)
    testsuites = json_data["testsuites"]

    if testsuites:
        status = "success" if testsuites[0]["failures"] == 0 else "failure"
    else:
        raise Exception(f"No testsuites found in the report! Raw data: {details}")

    template = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "group": None,
        "measurement": None,
        "result": None,
        "test_details": {
            "trigger_reason": trigger_reason,
            # Cluster attribution — every row emitted for this run is tagged
            # with the cluster it came from, so downstream Kusto queries can
            # group/filter by cluster across an N-cluster mesh test.
            "cluster": cluster_name,
            # mesh_size is the configured target N (from pipeline matrix);
            # cluster_count is what was actually discovered at run time. Querying
            # `mesh_size != cluster_count` in Kusto surfaces partial-mesh runs
            # (e.g., a Fleet member that failed to join) without needing a join
            # to control-plane logs.
            "mesh_size": mesh_size,
            "cluster_count": cluster_count,
            "namespaces": namespaces,
            "deployments_per_namespace": deployments_per_namespace,
            "replicas_per_deployment": replicas_per_deployment,
            "pods_per_cluster": namespaces * deployments_per_namespace * replicas_per_deployment,
            # Phase 4a — pod-churn knobs. Defaults are 0/"" for non-churn
            # test_types so existing Kusto queries that don't reference
            # these fields stay valid. For pod-churn runs these record the
            # exact stressor parameters so historical comparisons survive
            # default changes.
            "churn_cycles": churn_cycles,
            "churn_up_duration": churn_up_duration,
            "churn_down_duration": churn_down_duration,
            "kill_duration_seconds": kill_duration_seconds,
            "kill_interval_seconds": kill_interval_seconds,
            "kill_batch": kill_batch,
            "details": (
                testsuites[0]["testcases"][0].get("failure", None)
                if testsuites[0].get("testcases")
                else None
            ),
        },
        "cloud_info": cloud_info,
        "run_id": run_id,
        "run_url": run_url,
        "test_type": test_type,
        "start_timestamp": start_timestamp,
        # parameters (top-level for Kusto column convenience)
        "cluster": cluster_name,
        "mesh_size": mesh_size,
        "cluster_count": cluster_count,
        "namespaces": namespaces,
        "deployments_per_namespace": deployments_per_namespace,
        "replicas_per_deployment": replicas_per_deployment,
        "churn_cycles": churn_cycles,
        "kill_duration_seconds": kill_duration_seconds,
        "kill_interval_seconds": kill_interval_seconds,
        "kill_batch": kill_batch,
    }
    # Shared process_cl2_reports() does an unconditional open() on every
    # entry of cl2_report_dir, which raises IsADirectoryError on any subdir.
    # Today the only subdir is logs/ (created by run-cl2-on-cluster.sh for
    # pod-log capture), but we stash ANY subdir so future additions (new
    # diag dumps, CL2 version bump emitting per-phase subdirs, etc.) don't
    # silently regress. Subdirs are relocated OUTSIDE cl2_report_dir for
    # the duration of the parse and restored in a finally block — they
    # must end up back inside cl2_report_dir so the pipeline-level
    # artifact publish picks them up alongside junit.xml.
    stash_root = None
    stashed_entries = []
    for entry in os.listdir(cl2_report_dir):
        if os.path.isdir(os.path.join(cl2_report_dir, entry)):
            if stash_root is None:
                stash_root = tempfile.mkdtemp(prefix="cl2-report-stash-")
            os.rename(
                os.path.join(cl2_report_dir, entry),
                os.path.join(stash_root, entry),
            )
            stashed_entries.append(entry)
    try:
        content = process_cl2_reports(cl2_report_dir, template)
    finally:
        if stash_root:
            for entry in stashed_entries:
                src = os.path.join(stash_root, entry)
                if os.path.isdir(src):
                    os.rename(src, os.path.join(cl2_report_dir, entry))
            if not os.listdir(stash_root):
                os.rmdir(stash_root)

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(content)

    # Phase 4b — Scenario #4 (ClusterMesh APIServer Failure) timing pickup.
    # apiserver-failure-killer.sh writes ApiserverFailureTimings_<context>.json
    # at the target cluster's report dir with t0/t1/duration. Non-target
    # clusters skip writing the file. process_cl2_reports() doesn't recognize
    # this file pattern, so we emit the row explicitly here. One row per
    # timing file (always exactly one — only the target cluster writes one).
    _emit_apiserver_failure_timing_rows(cl2_report_dir, template, result_file)

    # Phase 4b — Scenario #7 (HA Configuration Validation) scaling pickup.
    # ha-config-scaler.sh writes HAConfigScalingTimings_<context>.json on
    # EVERY cluster (not just the kill target) — HA scaling is mesh-wide.
    # One row per cluster.
    _emit_ha_config_scaling_rows(cl2_report_dir, template, result_file)

    # Phase 4b — Scenario #3 (Node Churn / IP Churn) timing pickup.
    # node-churner.sh writes NodeChurnTimings_<target_context>.json into the
    # TARGET cluster's per-cluster report dir (the churner runs from
    # execute.yml on the AzDO agent, not inside CL2 — see plan.md scenario #3
    # design). One row per recorded op (scale_up / scale_down / replace_drain /
    # replace_delete / replace_wait). Non-target clusters skip writing the
    # file → no rows emitted for them.
    _emit_node_churn_timing_rows(cl2_report_dir, template, result_file)

    # Phase 4b — Scenario #6 (Upper Bound / Saturation) classifier rows.
    # Reads per-rung GenericPrometheusQuery output JSONs (one per measurement
    # × rung; CL2 emits them with the rung's suffix in the Identifier and
    # filename), applies the saturation classifier to each rung, and emits
    # one SaturationRung row per rung + one SaturationSummary row per
    # cluster. No-op when saturation_qps_list is empty (i.e. not an
    # upper-bound test_type) so non-saturation scenarios pay zero overhead.
    _emit_saturation_profile_rows(
        cl2_report_dir, template, result_file,
        saturation_qps_list, saturation_restarts_list,
    )


def _emit_saturation_profile_rows(
    cl2_report_dir, template, result_file,
    saturation_qps_list, saturation_restarts_list,
):
    """Append SaturationRung + SaturationSummary JSONL rows.

    Reads per-rung GenericPrometheusQuery output JSONs (CL2-emitted, format
    {"version": "v1", "dataItems": [{"labels": {"Metric": <query_name>},
    "data": {"value": <number>}}, ...]}) and applies the classifier.

    Args:
        cl2_report_dir: per-cluster report directory.
        template: row template (cluster/mesh_size/etc. already filled in).
        result_file: per-cluster JSONL output path (appended).
        saturation_qps_list: comma-separated QPS values, one per rung.
                             Empty string → not an upper-bound run → no-op.
        saturation_restarts_list: comma-separated restart counts, one per
                                  rung. Length must match qps_list; if not,
                                  missing entries default to 1.

    Emitted rows (one per rung + one per cluster summary):
        SaturationRung: {
            "rung_index": int,
            "configured_qps": int,
            "configured_restarts": int,
            "classifier_version": str,
            "thresholds": {<criterion>: float},
            "verdict": str,  # clean | latency_spike | queue_unbounded |
                             # cpu_exhaust | mesh_failure_burst | etcd_tail
            "dominant_signal_ratio": float,
            "rung_completed": bool,
            "measurement_missing": [str],
            "signals": {<name>: float|None},
            "all_verdicts": {<criterion>: float},  # ratio observed/threshold
        }
        SaturationSummary: {
            "rungs_configured": int,
            "rungs_completed": int,
            "max_clean_qps": int|None,  # highest QPS in contiguous clean prefix
            "first_failure_rung_index": int|None,
            "first_failure_qps": int|None,
            "first_failure_mode": str|None,
            "second_failure_mode": str|None,
            "classifier_version": str,
        }
    """
    if not saturation_qps_list:
        return  # Not an upper-bound run; no-op.
    try:
        qps_list = [int(x) for x in saturation_qps_list.split(",") if x.strip()]
    except ValueError as e:
        print(
            f"[collect] WARN: malformed saturation_qps_list "
            f"{saturation_qps_list!r}: {e}; skipping saturation classifier",
            file=sys.stderr,
        )
        return
    if not qps_list:
        return
    try:
        restarts_list = [
            int(x) for x in (saturation_restarts_list or "").split(",")
            if x.strip()
        ]
    except ValueError:
        restarts_list = []
    # Pad/truncate restarts_list to match qps_list length. Missing entries
    # default to 1 (the smallest meaningful restart count). Excess entries
    # are ignored.
    while len(restarts_list) < len(qps_list):
        restarts_list.append(1)
    restarts_list = restarts_list[: len(qps_list)]

    if not os.path.isdir(cl2_report_dir):
        print(
            f"[collect] WARN: saturation classifier: report dir "
            f"{cl2_report_dir} does not exist",
            file=sys.stderr,
        )
        return
    all_files = os.listdir(cl2_report_dir)

    # Proactive debug: dump the full list of rung-suffixed measurement files
    # so postmortem doesn't depend on the AzDO step's stdout being preserved.
    # User direction 2026-05-14: assume failure, keep debug logs baked in
    # until n=2 + n=20 are green; strip after.
    #
    # Match BOTH filename conventions:
    #   prod:    "GenericPrometheusQuery <metricName>  Rung<N>_<group>_<ts>.json"
    #            (space between method and metricName; verified build 67211)
    #   compact: "GenericPrometheusQuery_<MetricName>Rung<N>_<group>_<ts>.json"
    #            (no spaces; legacy mock convention)
    # Pre-fix (build 67221) the diagnostic counted only compact-form files,
    # so we'd see "0 found" even when files DID land via prod-form (the
    # _find_file lookup correctly accepts both, but the diagnostic was
    # misleading). Fix: count any GenericPrometheusQuery*.json with Rung<N>
    # in the name.
    rung_files_seen = sorted([
        f for f in all_files
        if f.startswith("GenericPrometheusQuery")
        and "Rung" in f
        and f.endswith(".json")
    ])
    print(
        f"[collect] saturation: classifier starting for "
        f"qps_list={qps_list} restarts_list={restarts_list}",
        file=sys.stderr,
    )
    print(
        f"[collect] saturation: cl2_report_dir={cl2_report_dir} "
        f"total_files_in_dir={len(all_files)} "
        f"rung_files_matching_pattern={len(rung_files_seen)}",
        file=sys.stderr,
    )
    # Print ALL files (not just rung ones) so if the prefix matcher has any
    # encoding/whitespace surprise, the raw listing reveals it.
    for fname in all_files[:30]:
        print(f"[collect] saturation:   listdir: {fname!r}", file=sys.stderr)
    if len(all_files) > 30:
        print(
            f"[collect] saturation:   ... and {len(all_files) - 30} more",
            file=sys.stderr,
        )

    def _read_metric(filepath, metric_label):
        """Return the numeric `value` for a given Metric label, or None.

        Supports BOTH known CL2 dataItem shapes:

          (A) CL2 GenericPrometheusQuery — one dataItem with all query
              results as named keys in `data` (verified against build 67224):
                {"dataItems": [{"data": {"Max": 0, "Perc99": 0.5}, "unit": "#"}]}
              The metric_label is the query name from the YAML
              (Max / Perc50 / Perc99 / etc.) and is looked up directly as a
              dict key inside item.data.

          (B) Legacy / PodStartupLatency-style — one dataItem per metric,
              with labels.Metric naming the metric and data.value holding
              the number:
                {"dataItems": [
                    {"labels": {"Metric": "Perc99"}, "data": {"value": 0.5}}
                ]}

        Returns the first match across all dataItems. None if the label
        isn't present in any item or the file can't be parsed.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(
                f"[collect] WARN: failed to read {filepath}: {e}",
                file=sys.stderr,
            )
            return None
        for item in data.get("dataItems", []) or []:
            item_data = item.get("data") or {}
            # Format A: query name (e.g. "Perc99") is a direct key in
            # item.data. The value is the scalar number (not a {"value": N}
            # wrapper). Skip dict-valued entries so we don't accidentally
            # match a legacy nested structure.
            if metric_label in item_data and not isinstance(
                item_data[metric_label], (dict, list)
            ):
                val = item_data[metric_label]
                if val is None or val == "":
                    return None
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None
            # Format B: labels.Metric carries the query name, data.value
            # carries the scalar number. Backward-compatible with existing
            # mock fixtures (PodStartupLatency mock_data).
            labels = item.get("labels") or {}
            if labels.get("Metric") == metric_label:
                val = item_data.get("value")
                if val is None or val == "":
                    return None
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None
        return None

    def _find_file(rung_suffix, metric_name_prefix):
        """Locate the CL2-emitted JSON for a given metricName prefix and
        rung suffix. CL2's actual file pattern (verified against build 67211)
        is:
            GenericPrometheusQuery <metricName with spaces> <suffix>_<group>_<timestamp>.json

        e.g. for metricName "ClusterMesh Kvstore Sync Queue Size {{$suffix}}"
        with suffix=Rung0:
            GenericPrometheusQuery ClusterMesh Kvstore Sync Queue Size Rung0_clustermesh-upper-bound_2026-05-15T02:20:27Z.json

        We match on the production format primarily, with a fallback to the
        compact-no-space underscore format
            GenericPrometheusQuery_<MetricNameNoSpaces><Suffix>_<group>_<ts>.json
        for backward compat with mock fixtures + any other CL2 versions
        that strip spaces.
        """
        # Production format (build 67211 confirmed): space-separated, suffix
        # immediately follows metric name with a space (because the YAML
        # template `metricName: <name> {{$suffix}}` keeps the space).
        prod_target = f"GenericPrometheusQuery {metric_name_prefix} {rung_suffix}_"
        # Mock/compact fallback: drop spaces, no leading space after method.
        compact_metric = metric_name_prefix.replace(" ", "")
        compact_target = f"GenericPrometheusQuery_{compact_metric}{rung_suffix}_"
        matches = [
            f for f in all_files
            if (f.startswith(prod_target) or f.startswith(compact_target))
            and f.endswith(".json")
        ]
        if matches:
            return os.path.join(cl2_report_dir, matches[0])
        return None

    # Signal name → (metricName-from-YAML, metric-label, transform).
    # The metricName is the YAML's `metricName:` field text (space-separated),
    # which is what CL2 embeds in the emitted filename. Build 67211 verified
    # the production filename pattern.
    #
    # Transform converts the measurement's native unit into the classifier's
    # threshold unit (seconds → milliseconds where applicable).
    signal_map = {
        "latency_p99_ms": (
            "ClusterMesh Kvstore Operation Duration", "Perc99",
            lambda v: v * 1000.0,
        ),
        "queue_size_perc99": (
            "ClusterMesh Kvstore Sync Queue Size", "Perc99",
            lambda v: v,
        ),
        "queue_size_max": (
            "ClusterMesh Kvstore Sync Queue Size", "Max",
            lambda v: v,
        ),
        "apiserver_max_cpu_cores": (
            "ClusterMesh APIServer Pod CPU", "PerPodMax",
            lambda v: v,
        ),
        "mesh_failure_rate_max": (
            "ClusterMesh Remote Cluster Failure Rate", "Max",
            lambda v: v,
        ),
        "etcd_commit_p99_ms": (
            "ClusterMesh Etcd Backend Write Duration", "Perc99",
            lambda v: v * 1000.0,
        ),
        "observed_event_rate_p99": (
            "ClusterMesh Kvstore Events Rate", "Perc99",
            lambda v: v,
        ),
    }
    # Criterion → signal-name driving the verdict. Each criterion's ratio
    # is observed/threshold; ≥1.0 = tripped. Dominant criterion = the
    # tripped one with the highest ratio.
    criteria = {
        "latency_spike": "latency_p99_ms",
        "queue_unbounded": "queue_size_perc99",
        "cpu_exhaust": "apiserver_max_cpu_cores",
        "mesh_failure_burst": "mesh_failure_rate_max",
        "etcd_tail": "etcd_commit_p99_ms",
    }

    rungs_completed = 0
    first_failure_index = None
    first_failure_qps = None
    first_failure_mode = None
    second_failure_mode = None
    max_clean_qps = None
    clean_streak_broken = False

    with open(result_file, "a", encoding="utf-8") as out:
        for rung_idx, qps in enumerate(qps_list):
            suffix = f"Rung{rung_idx}"
            restarts = restarts_list[rung_idx]

            signals = {}
            measurement_missing = []
            for sig_name, (ident, metric_label, transform) in signal_map.items():
                fpath = _find_file(suffix, ident)
                if fpath is None:
                    signals[sig_name] = None
                    measurement_missing.append(sig_name)
                    continue
                raw = _read_metric(fpath, metric_label)
                if raw is None:
                    signals[sig_name] = None
                    measurement_missing.append(sig_name)
                else:
                    signals[sig_name] = transform(raw)

            # Rung "completed" iff at least one signal landed AND the
            # latency signal landed (proxy for "the rung executed and CL2
            # gathered measurements for it"). Tuned conservatively so a
            # half-collected rung is flagged for re-investigation rather
            # than silently summarized.
            rung_completed = (
                signals.get("latency_p99_ms") is not None
                and len(measurement_missing) < len(signal_map)
            )
            if rung_completed:
                rungs_completed += 1

            # Compute per-criterion ratios. None signals = criterion
            # skipped (cannot contribute to verdict).
            all_verdicts = {}
            for criterion, sig_name in criteria.items():
                v = signals.get(sig_name)
                if v is None:
                    continue
                threshold = SATURATION_THRESHOLDS[
                    sig_name if sig_name in SATURATION_THRESHOLDS
                    else "latency_p99_ms"  # never hits — defensive
                ]
                if threshold <= 0:
                    continue
                all_verdicts[criterion] = v / threshold

            tripped = {c: r for c, r in all_verdicts.items() if r >= 1.0}
            if tripped:
                verdict = max(tripped, key=tripped.get)
                dominant_ratio = tripped[verdict]
            elif (not rung_completed and rungs_completed > 0):
                # Phase 4b — Scenario #6 monitoring_oom verdict (added
                # 2026-05-15 after build 67279 showed Prometheus crashed
                # mid-run at Rung 2-3, losing all measurements for those
                # rungs). When an earlier rung completed but the current
                # rung's measurements all came back empty, the most likely
                # explanation is that the monitoring stack (Prometheus
                # pod) ran out of memory / went CrashLoopBackOff under
                # the elevated workload pressure of the higher rung.
                # That IS a saturation finding per spec line 113
                # ("Resource exhaustion occurs") — record it as a real
                # verdict instead of silently leaving the rung as
                # verdict=clean rung_completed=False which underclaims
                # the failure.
                #
                # Synthetic dominant_signal_ratio=999.0 so dashboards
                # ordering verdicts by severity rank this above other
                # tripped criteria. The actual signal that drove the
                # OOM (CPU, memory, query queue, cardinality explosion)
                # is NOT distinguishable from blob output alone — needs
                # Prom pod logs to triage.
                verdict = "monitoring_oom"
                dominant_ratio = 999.0
            else:
                verdict = "clean"
                dominant_ratio = max(all_verdicts.values()) if all_verdicts else 0.0

            # Track per-cluster summary fields. max_clean_qps is the
            # highest qps in a CONTIGUOUS clean+completed prefix — once
            # a non-clean rung lands we stop extending it (a brief
            # later-rung "false clean" shouldn't disqualify the genuine
            # earlier failure).
            if verdict == "clean" and rung_completed and not clean_streak_broken:
                if max_clean_qps is None or qps > max_clean_qps:
                    max_clean_qps = qps
            else:
                clean_streak_broken = True
                if verdict != "clean":
                    if first_failure_index is None:
                        first_failure_index = rung_idx
                        first_failure_qps = qps
                        first_failure_mode = verdict
                    elif (second_failure_mode is None
                          and verdict != first_failure_mode):
                        second_failure_mode = verdict

            rung_row = json.loads(json.dumps(template))
            rung_row["measurement"] = "SaturationRung"
            rung_row["group"] = "upper-bound"
            rung_row["result"] = {
                "data": {
                    "rung_index": rung_idx,
                    "configured_qps": qps,
                    "configured_restarts": restarts,
                    "classifier_version": SATURATION_CLASSIFIER_VERSION,
                    "thresholds": SATURATION_THRESHOLDS,
                    "verdict": verdict,
                    "dominant_signal_ratio": dominant_ratio,
                    "rung_completed": rung_completed,
                    "measurement_missing": measurement_missing,
                    "signals": signals,
                    "all_verdicts": all_verdicts,
                },
                "unit": "verdict",
            }
            out.write(json.dumps(rung_row) + "\n")

            # Per-rung stderr summary: greppable line for AzDO postmortem
            # ("collect saturation rung=2 verdict=queue_unbounded ratio=5.0").
            # Counts signals found out of expected so partial rungs surface.
            print(
                f"[collect] saturation: rung={rung_idx} qps={qps} "
                f"restarts={restarts} verdict={verdict} "
                f"dominant_ratio={dominant_ratio:.3f} "
                f"completed={rung_completed} "
                f"signals_found={len(signal_map) - len(measurement_missing)}/{len(signal_map)} "
                f"missing={measurement_missing}",
                file=sys.stderr,
            )

        summary_row = json.loads(json.dumps(template))
        summary_row["measurement"] = "SaturationSummary"
        summary_row["group"] = "upper-bound"
        summary_row["result"] = {
            "data": {
                "rungs_configured": len(qps_list),
                "rungs_completed": rungs_completed,
                "max_clean_qps": max_clean_qps,
                "first_failure_rung_index": first_failure_index,
                "first_failure_qps": first_failure_qps,
                "first_failure_mode": first_failure_mode,
                "second_failure_mode": second_failure_mode,
                "configured_qps_list": qps_list,
                "configured_restarts_list": restarts_list,
                "classifier_version": SATURATION_CLASSIFIER_VERSION,
                "thresholds": SATURATION_THRESHOLDS,
            },
            "unit": "verdict",
        }
        out.write(json.dumps(summary_row) + "\n")

        # Stderr summary for AzDO postmortem; greppable headline line.
        print(
            f"[collect] saturation: SUMMARY rungs_completed={rungs_completed}/{len(qps_list)} "
            f"max_clean_qps={max_clean_qps} "
            f"first_failure_qps={first_failure_qps} "
            f"first_failure_mode={first_failure_mode} "
            f"second_failure_mode={second_failure_mode} "
            f"classifier_version={SATURATION_CLASSIFIER_VERSION}",
            file=sys.stderr,
        )


def _emit_node_churn_timing_rows(cl2_report_dir, template, result_file):
    """Append one JSONL row per recorded op in NodeChurnTimings_*.json.

    File shape (from node-churner.sh):
        {
          "target_context": str,
          "target_cluster_name": str,
          "target_resource_group": str,
          "target_nodepool": str,
          "scenario": "node-churn-scale" | "node-churn-replace" | "node-churn-combined",
          "original_node_count": int,
          "ready_quorum_reached": bool,
          "cleanup_failed": bool,
          "scenario_valid": bool,         // false if a circuit-breaker fired
          "truncated": bool,              // true if churner ran past CL2 sleep
          "started_epoch": int,
          "ended_epoch": int,
          "duration_seconds": int,
          "ops": [
            {
              "op_index": int,
              "op_type": "scale_up"|"scale_down"|"replace_drain"|"replace_delete"|"replace_refill"|"replace_wait",
              "start_epoch": int,
              "end_epoch": int,
              "duration_seconds": int,
              "succeeded": bool,
              "observed_node_count": int,
              "pre_ip_set": [str],         // only populated on replace_wait
              "post_ip_set": [str],
              "pre_node_names": [str],     // only populated on replace_wait
              "post_node_names": [str],
              "new_ip_count": int,         // INFORMATIONAL — Azure VNet allocator
                                           // reuses freed IPs immediately so this
                                           // may be 0 even after successful replacement
              "new_node_count": int,       // AUTHORITATIVE replacement signal —
                                           // VMSS instance IDs are monotonic so node
                                           // names always differ after replacement
              "error": str                 // empty on success
            }, ...
          ]
        }

    Each op becomes one row in the JSONL with
    measurement="NodeChurnOpTiming", group=<scenario>, and result.data = the
    per-op JSON, PLUS scenario-level fields copied onto result.data for
    cross-row context (scenario_valid, cleanup_failed, truncated, etc.).
    A scenario-level summary row with measurement="NodeChurnSummary" is also
    emitted so Kusto queries can detect cleanup_failed / scenario_valid=false
    runs without joining op rows. One summary row per timing file.
    """
    timing_files = [
        f for f in os.listdir(cl2_report_dir)
        if f.startswith("NodeChurnTimings_") and f.endswith(".json")
    ]
    if not timing_files:
        return
    scenario_level_keys = (
        "scenario", "target_context", "target_cluster_name",
        "target_resource_group", "target_nodepool",
        "original_node_count", "ready_quorum_reached", "cleanup_failed",
        "scenario_valid", "truncated", "started_epoch", "ended_epoch",
        "duration_seconds",
    )
    with open(result_file, "a", encoding="utf-8") as out:
        for tf in timing_files:
            tf_path = os.path.join(cl2_report_dir, tf)
            try:
                with open(tf_path, "r", encoding="utf-8") as tfh:
                    timing_data = json.load(tfh)
            except (OSError, json.JSONDecodeError) as e:
                print(
                    f"[collect] WARN: failed to read {tf_path}: {e}",
                    file=sys.stderr,
                )
                continue
            scenario_context = {
                k: timing_data.get(k) for k in scenario_level_keys
            }
            # One summary row per file — always emitted, even if ops list is
            # empty (e.g., quorum never reached → churner aborted before any op).
            summary_row = json.loads(json.dumps(template))
            summary_row["measurement"] = "NodeChurnSummary"
            summary_row["group"] = timing_data.get("scenario", "node-churn")
            summary_row["result"] = {
                "data": {
                    **scenario_context,
                    "op_count": len(timing_data.get("ops") or []),
                },
                "unit": "seconds",
            }
            out.write(json.dumps(summary_row) + "\n")
            # One row per op, with scenario_context merged onto result.data so
            # a single Kusto filter (e.g., scenario_valid=true) gates op-level
            # analysis without needing a join.
            for op in timing_data.get("ops") or []:
                op_row = json.loads(json.dumps(template))
                op_row["measurement"] = "NodeChurnOpTiming"
                op_row["group"] = timing_data.get("scenario", "node-churn")
                op_row["result"] = {
                    "data": {**scenario_context, **op},
                    "unit": "seconds",
                }
                out.write(json.dumps(op_row) + "\n")


def _emit_apiserver_failure_timing_rows(cl2_report_dir, template, result_file):
    """Append one JSONL row per ApiserverFailureTimings_*.json found.

    The timing file shape (from apiserver-failure-killer.sh):
        {
          "target_context": str,
          "t0_kill_epoch": int,
          "t1_recovered_epoch": int,
          "recovery_duration_seconds": int,
          "recovered": bool,
          "killed_pod_name": str,
          "killed_pod_uid": str,
          "replacement_pod_uid": str,
          "note": str
        }

    Each timing file becomes one row in the JSONL with
    measurement="ApiserverFailureRecoveryTiming", group="apiserver-failure",
    and result.data = the timing JSON. Downstream Kusto queries can filter
    on this measurement name to get per-run recovery timings keyed by
    test_type=apiserver-failure + cluster.
    """
    timing_files = [
        f for f in os.listdir(cl2_report_dir)
        if f.startswith("ApiserverFailureTimings_") and f.endswith(".json")
    ]
    if not timing_files:
        return
    with open(result_file, "a", encoding="utf-8") as out:
        for tf in timing_files:
            tf_path = os.path.join(cl2_report_dir, tf)
            try:
                with open(tf_path, "r", encoding="utf-8") as tfh:
                    timing_data = json.load(tfh)
            except (OSError, json.JSONDecodeError) as e:
                print(
                    f"[collect] WARN: failed to read {tf_path}: {e}",
                    file=sys.stderr,
                )
                continue
            # Deep-copy template so we don't mutate the shared dict for any
            # downstream caller.
            row = json.loads(json.dumps(template))
            row["measurement"] = "ApiserverFailureRecoveryTiming"
            row["group"] = "apiserver-failure"
            row["result"] = {"data": timing_data, "unit": "seconds"}
            out.write(json.dumps(row) + "\n")


def _emit_ha_config_scaling_rows(cl2_report_dir, template, result_file):
    """Append one JSONL row per HAConfigScalingTimings_*.json found.

    The scaling file shape (from ha-config-scaler.sh):
        {
          "context": str,
          "action": "scale-up" | "scale-down",
          "requested_replicas": int,
          "spec_replicas_after": int,
          "ready_replicas_after": int,
          "ha_replicas_honored": bool,
          "scale_duration_seconds": int,
          "note": str
        }

    Each file becomes one row in the JSONL with
    measurement="HAConfigScalingTiming", group="ha-config", and
    result.data = the scaling JSON. Only scale-up emits a file; scale-down
    is best-effort cleanup that does NOT overwrite the scale-up file.
    Downstream Kusto queries can filter on measurement="HAConfigScalingTiming"
    and ha_replicas_honored=true to scope HA A/B comparisons to runs where
    the scale actually stuck (ENO operator did not revert).
    """
    timing_files = [
        f for f in os.listdir(cl2_report_dir)
        if f.startswith("HAConfigScalingTimings_") and f.endswith(".json")
    ]
    if not timing_files:
        return
    with open(result_file, "a", encoding="utf-8") as out:
        for tf in timing_files:
            tf_path = os.path.join(cl2_report_dir, tf)
            try:
                with open(tf_path, "r", encoding="utf-8") as tfh:
                    scaling_data = json.load(tfh)
            except (OSError, json.JSONDecodeError) as e:
                print(
                    f"[collect] WARN: failed to read {tf_path}: {e}",
                    file=sys.stderr,
                )
                continue
            row = json.loads(json.dumps(template))
            row["measurement"] = "HAConfigScalingTiming"
            row["group"] = "ha-config"
            row["result"] = {"data": scaling_data, "unit": "seconds"}
            out.write(json.dumps(row) + "\n")


def main():
    parser = argparse.ArgumentParser(description="ClusterMesh scale-test harness.")
    subparsers = parser.add_subparsers(dest="command")

    # configure
    pc = subparsers.add_parser("configure", help="Write CL2 overrides file")
    pc.add_argument("--namespaces", type=int, required=True)
    pc.add_argument("--deployments-per-namespace", type=int, required=True)
    pc.add_argument("--replicas-per-deployment", type=int, required=True)
    pc.add_argument("--operation-timeout", type=str, default="15m")
    pc.add_argument("--cl2_override_file", type=str, required=True,
                    help="Path to the overrides of CL2 config file")
    # Phase 4a — Scenario #2 (Pod Churn Stress) knobs. Defaults match the
    # pipeline matrix defaults so a configure invocation that doesn't pass
    # these still writes valid overrides for both pod-churn-scale.yaml and
    # pod-churn-kill.yaml.
    pc.add_argument("--churn-cycles", type=int, default=5,
                    help="Number of scale-up/down cycles (pod-churn-scale).")
    pc.add_argument("--churn-up-duration", type=str, default="60s",
                    help="Sleep between scale-up and next scale-down (pod-churn-scale).")
    pc.add_argument("--churn-down-duration", type=str, default="60s",
                    help="Sleep between scale-down and next scale-up (pod-churn-scale).")
    pc.add_argument("--kill-duration", type=str, default="10m",
                    help="Total kill-loop duration as a human string (logged only). "
                         "The runtime is bounded by --kill-duration-seconds.")
    pc.add_argument("--kill-interval-seconds", type=int, default=10,
                    help="Seconds between successive kill rounds (pod-churn-kill).")
    pc.add_argument("--kill-batch", type=int, default=5,
                    help="Pods deleted per round (pod-churn-kill).")
    pc.add_argument("--kill-duration-seconds", type=int, default=600,
                    help="Killer Job script runtime in seconds (pod-churn-kill).")
    pc.add_argument("--kill-job-deadline-seconds", type=int, default=660,
                    help="Killer Job activeDeadlineSeconds — defense-in-depth bound, "
                         "should be kill_duration_seconds plus a small buffer.")
    # Phase 4b — Scenario #4 (ClusterMesh APIServer Failure) knobs.
    pc.add_argument("--apiserver-kill-target-context", type=str, default="clustermesh-1",
                    help="kubectl context name of the cluster whose clustermesh-apiserver "
                         "to kill. Other clusters no-op (per-cluster CL2 with shared overrides).")
    pc.add_argument("--apiserver-kill-recovery-timeout-seconds", type=int, default=240,
                    help="How long to wait for the replacement clustermesh-apiserver pod "
                         "to reach Ready after kill. AKS-managed Cilium can take "
                         "120-180s in our observed runs (image pull + ENI attach); "
                         "240s gives headroom. Killer fails soft on timeout — writes "
                         "timing JSON with recovered:false instead of erroring.")
    pc.add_argument("--apiserver-kill-observation-seconds", type=int, default=60,
                    help="Sleep duration AFTER the kill returns, before measurement gather. "
                         "Lets peer clusters' Prometheus scrape the failure window and "
                         "the post-recovery backlog drain.")
    # Phase 4b — Scenario #7 (HA Configuration Validation) knob.
    pc.add_argument("--ha-config-replicas", type=int, default=3,
                    help="Target replicas count for clustermesh-apiserver Deployment "
                         "during the ha-config scenario. Each cluster scales its own "
                         "Deployment to this count before measurements start, then back "
                         "to 1 after gather. Default 3 (standard k8s HA, etcd quorum-friendly).")
    # Phase 4b — Scenario #3 (Node Churn / IP Churn) knobs.
    # CL2 templates that don't reference these silently ignore (same pattern
    # as the apiserver / ha-config knobs). node-churner.sh consumes them via
    # matrix-exported env vars in execute.yml — NOT via these overrides.
    pc.add_argument("--node-churn-target-context", type=str, default="clustermesh-1",
                    help="kubectl context name of the cluster whose default nodepool "
                         "is scaled / replaced. Other clusters observe via CL2. "
                         "Reuses the apiserver-failure target convention.")
    pc.add_argument("--node-churn-cycles", type=int, default=3,
                    help="Number of scale-up/down cycles in node-churn-scale. "
                         "Each cycle does ONE scale-up by --node-churn-delta then ONE "
                         "scale-down by the same delta with --node-churn-settle-seconds "
                         "between ops. 3 cycles × 2 ops × ~4min/op = ~24min wall.")
    pc.add_argument("--node-churn-delta", type=int, default=5,
                    help="Per-half-cycle scale delta. +N on scale-up, -N on scale-down. "
                         "Default 5 → 20→25→20 cycles. Bounded above by AKS vCPU quota.")
    pc.add_argument("--node-churn-settle-seconds", type=int, default=60,
                    help="Sleep between consecutive nodepool ops to let cilium "
                         "reconcile node identities + endpoints before next op.")
    pc.add_argument("--node-churn-scale-duration-seconds", type=int, default=1800,
                    help="CL2-side sleep window for node-churn-scale.yaml. Must be "
                         "≥ expected churner wall time + settle margin. 1800s = 30min "
                         "covers 3-cycle scale at ~24min churner wall.")
    pc.add_argument("--node-churn-replace-duration-seconds", type=int, default=1500,
                    help="CL2-side sleep window for node-churn-replace.yaml. "
                         "1500s = 25min covers VMSS-delete-and-replace of ~10 instances "
                         "in parallel (each drain+replace ~5-10min, parallelized).")
    pc.add_argument("--node-churn-combined-duration-seconds", type=int, default=3300,
                    help="CL2-side sleep window for node-churn-combined.yaml "
                         "(scale phase + replace phase serially). Sum of the two "
                         "individual windows plus margin.")
    pc.add_argument("--node-replace-batch-size", type=int, default=10,
                    help="Number of VMSS instances to drain+delete in the replace "
                         "scenario. AKS auto-replaces to restore the desired count, "
                         "yielding K new VMs with new IPs. 10 of 20 default nodes = "
                         "50%% pool replacement; bounded above by --max-surge fraction "
                         "Cilium can tolerate without endpoint floods saturating the mesh.")
    pc.add_argument("--node-churn-ready-timeout-seconds", type=int, default=300,
                    help="How long node-churner.sh waits for per-cluster CL2 ready "
                         "sentinels before starting the first nodepool op. If quorum "
                         "(all clusters' sentinels) isn't reached within this window, "
                         "the churner aborts WITH cleanup (restores pool to original "
                         "node count) and marks scenario_valid=false in the timing JSON.")
    # Phase 4b — Scenario #6 (Upper Bound / Saturation) knobs.
    # Each upper-bound CL2 run sweeps through N rungs of progressively
    # heavier load (QPS × restart count). The classifier in collect emits
    # one SaturationRung row per rung tagging which signal tripped
    # (clean | latency_spike | queue_unbounded | cpu_exhaust |
    # mesh_failure_burst | etcd_tail). See SATURATION_THRESHOLDS at the
    # top of this module + plan.md Scenario #6 section.
    pc.add_argument("--saturation-qps-list", type=str, default="100,500,1500,4000,10000",
                    help="Comma-separated list of QPS values, one per saturation "
                         "rung. Length determines number of rungs; CL2's "
                         "upper-bound.yaml parses this via StringSplit. "
                         "Default is a 5-rung sweep (100, 500, 1500, 4000, 10000 "
                         "calls/sec) — bumped 2026-05-15 after build 67224 showed "
                         "all signals at 1-15%% of thresholds at the prior top rung "
                         "(qps=160, restarts=4). QPS above ~100 is effectively "
                         "uncapped for our 20-deployment workload (CL2 apply "
                         "throughput is the ceiling, not QPS itself); "
                         "saturation_restarts_list is the real load lever.")
    pc.add_argument("--saturation-restarts-list", type=str, default="2,4,8,15,25",
                    help="Comma-separated list of restart counts, one per saturation "
                         "rung (length must match --saturation-qps-list). Each rung's "
                         "workload is restart-bursted this many times so cumulative "
                         "event volume scales with rung index even when CL2's "
                         "Deployment-apply QPS saturates. Restart count is the "
                         "primary load lever: each restart triggers ~200 pod recreates "
                         "(at n=2 with 200-pod workload), each emitting endpoint + "
                         "identity + service events through the mesh.")
    pc.add_argument("--saturation-rung-duration-seconds", type=int, default=240,
                    help="Wall-clock duration each rung holds after its restart-burst "
                         "before measurements are gathered. Drives the per-rung "
                         "measurement window (CL2 substitutes %%v in queries with "
                         "wall time since the matching `start` action). Bumped "
                         "180s\u2192240s 2026-05-15 to give higher rungs time to "
                         "accumulate meaningful signal at the post-burst tail.")
    pc.add_argument("--saturation-settle-seconds", type=int, default=90,
                    help="Sleep between rungs so kvstore queues from rung r drain "
                         "before rung r+1's measurement window opens. Insufficient "
                         "settle biases later rungs' verdicts toward `queue_unbounded` "
                         "even if the queue would have drained on its own. Bumped "
                         "60s\u219290s 2026-05-15 since higher restart bursts take "
                         "longer to fully drain queues.")

    # execute
    pe = subparsers.add_parser("execute", help="Run CL2 against a single cluster")
    pe.add_argument("--cl2-image", type=str, required=True)
    pe.add_argument("--cl2-config-dir", type=str, required=True)
    pe.add_argument("--cl2-report-dir", type=str, required=True)
    pe.add_argument("--cl2-config-file", type=str, required=True)
    pe.add_argument("--kubeconfig", type=str, required=True)
    pe.add_argument("--provider", type=str, required=True)
    pe.add_argument("--tear-down-prometheus", action="store_true",
                    help="Tear down Prometheus stack at end of CL2 (set in share-infra "
                         "mode so the next scenario's CL2 can deploy a fresh Prom). "
                         "Default is to preserve Prom for failure-diagnostic dumping.")

    # execute-parallel — fan out CL2 across N clusters with bounded concurrency
    pep = subparsers.add_parser(
        "execute-parallel",
        help="Run CL2 across multiple clusters with bounded concurrency",
    )
    pep.add_argument("--clusters", type=str, required=True,
                     help="Path to JSON file containing array of cluster objects, "
                          "each with at least 'role' and 'kubeconfig' fields")
    pep.add_argument("--max-concurrent", type=int, default=4,
                     help="Maximum number of CL2 invocations to run in parallel")
    pep.add_argument("--worker-script", type=str, required=True,
                     help="Path to per-cluster bash worker (run-cl2-on-cluster.sh)")
    pep.add_argument("--cl2-image", type=str, required=True)
    pep.add_argument("--cl2-config-dir", type=str, required=True)
    pep.add_argument("--cl2-config-file", type=str, required=True)
    pep.add_argument("--cl2-report-dir-base", type=str, required=True,
                     help="Base directory; per-cluster reports land at <base>/<role>/")
    pep.add_argument("--provider", type=str, required=True)
    pep.add_argument("--python-script-file", type=str, required=True,
                     help="Path to this scale.py — invoked by the worker script "
                          "via `python3 <path> execute ...`")
    pep.add_argument("--python-workdir", type=str, required=True,
                     help="Working dir for the nested python execute call "
                          "(typically modules/python so PYTHONPATH resolves)")
    pep.add_argument("--tear-down-prometheus", action="store_true",
                     help="Pass through to each per-cluster CL2 invocation; used in "
                          "share-infra mode where multiple scenarios share infra and "
                          "each needs a clean Prometheus deploy.")

    # collect
    pco = subparsers.add_parser("collect", help="Collect results for one cluster")
    pco.add_argument("--cl2_report_dir", type=str, required=True)
    pco.add_argument("--cloud_info", type=str, default="")
    pco.add_argument("--run_id", type=str, required=True)
    pco.add_argument("--run_url", type=str, default="")
    pco.add_argument("--result_file", type=str, required=True)
    pco.add_argument("--test_type", type=str, default="default-config")
    pco.add_argument("--start_timestamp", type=str, required=True)
    pco.add_argument("--cluster-name", type=str, required=True,
                     help="Fleet member / AKS cluster identity for attribution")
    pco.add_argument("--cluster-count", type=int, required=True,
                     help="Total clusters in the mesh for this run (N)")
    pco.add_argument("--mesh-size", type=int, required=True,
                     help="Configured target cluster count from the pipeline matrix; "
                          "compared against --cluster-count to detect partial-mesh runs")
    pco.add_argument("--namespaces", type=int, required=True)
    pco.add_argument("--deployments-per-namespace", type=int, required=True)
    pco.add_argument("--replicas-per-deployment", type=int, required=True)
    pco.add_argument("--trigger_reason", type=str, default="")
    # Phase 4a — pod-churn knobs recorded into the JSONL for historical
    # comparison. Optional; default to 0/"" so non-churn test_types
    # (event-throughput, default-config) don't need to set them.
    pco.add_argument("--churn-cycles", type=int, default=0)
    pco.add_argument("--churn-up-duration", type=str, default="")
    pco.add_argument("--churn-down-duration", type=str, default="")
    pco.add_argument("--kill-duration-seconds", type=int, default=0)
    pco.add_argument("--kill-interval-seconds", type=int, default=0)
    pco.add_argument("--kill-batch", type=int, default=0)
    # Phase 4b — Scenario #6 (Upper Bound / Saturation) collect knobs.
    # Optional; default to empty string so non-saturation test_types skip
    # the classifier entirely (zero overhead). For upper-bound test_types,
    # collect.yml plumbs the matrix-configured saturation_qps_list +
    # saturation_restarts_list into these args so the classifier records
    # the actual QPS and restart values that drove each rung.
    pco.add_argument("--saturation-qps-list", type=str, default="",
                     help="Comma-separated QPS values from the upper-bound run. "
                          "Empty = not an upper-bound run; classifier is no-op.")
    pco.add_argument("--saturation-restarts-list", type=str, default="",
                     help="Comma-separated restart counts from the upper-bound run "
                          "(length must match --saturation-qps-list).")

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(
            args.namespaces,
            args.deployments_per_namespace,
            args.replicas_per_deployment,
            args.operation_timeout,
            args.cl2_override_file,
            churn_cycles=args.churn_cycles,
            churn_up_duration=args.churn_up_duration,
            churn_down_duration=args.churn_down_duration,
            kill_duration=args.kill_duration,
            kill_interval_seconds=args.kill_interval_seconds,
            kill_batch=args.kill_batch,
            kill_duration_seconds=args.kill_duration_seconds,
            kill_job_deadline_seconds=args.kill_job_deadline_seconds,
            apiserver_kill_target_context=args.apiserver_kill_target_context,
            apiserver_kill_recovery_timeout_seconds=args.apiserver_kill_recovery_timeout_seconds,
            apiserver_kill_observation_seconds=args.apiserver_kill_observation_seconds,
            ha_config_replicas=args.ha_config_replicas,
            node_churn_target_context=args.node_churn_target_context,
            node_churn_cycles=args.node_churn_cycles,
            node_churn_delta=args.node_churn_delta,
            node_churn_settle_seconds=args.node_churn_settle_seconds,
            node_churn_scale_duration_seconds=args.node_churn_scale_duration_seconds,
            node_churn_replace_duration_seconds=args.node_churn_replace_duration_seconds,
            node_churn_combined_duration_seconds=args.node_churn_combined_duration_seconds,
            node_replace_batch_size=args.node_replace_batch_size,
            node_churn_ready_timeout_seconds=args.node_churn_ready_timeout_seconds,
            saturation_qps_list=args.saturation_qps_list,
            saturation_restarts_list=args.saturation_restarts_list,
            saturation_rung_duration_seconds=args.saturation_rung_duration_seconds,
            saturation_settle_seconds=args.saturation_settle_seconds,
        )
    elif args.command == "execute":
        execute_clusterloader2(
            args.cl2_image,
            args.cl2_config_dir,
            args.cl2_report_dir,
            args.cl2_config_file,
            args.kubeconfig,
            args.provider,
            tear_down_prometheus=args.tear_down_prometheus,
        )
    elif args.command == "execute-parallel":
        rc = execute_parallel(
            clusters_file=args.clusters,
            max_concurrent=args.max_concurrent,
            worker_script=args.worker_script,
            cl2_image=args.cl2_image,
            cl2_config_dir=args.cl2_config_dir,
            cl2_config_file=args.cl2_config_file,
            cl2_report_dir_base=args.cl2_report_dir_base,
            provider=args.provider,
            python_script_file=args.python_script_file,
            python_workdir=args.python_workdir,
            tear_down_prometheus=args.tear_down_prometheus,
        )
        sys.exit(rc)
    elif args.command == "collect":
        collect_clusterloader2(
            args.cl2_report_dir,
            args.cloud_info,
            args.run_id,
            args.run_url,
            args.result_file,
            args.test_type,
            args.start_timestamp,
            args.cluster_name,
            args.cluster_count,
            args.mesh_size,
            args.namespaces,
            args.deployments_per_namespace,
            args.replicas_per_deployment,
            args.trigger_reason,
            churn_cycles=args.churn_cycles,
            churn_up_duration=args.churn_up_duration,
            churn_down_duration=args.churn_down_duration,
            kill_duration_seconds=args.kill_duration_seconds,
            kill_interval_seconds=args.kill_interval_seconds,
            kill_batch=args.kill_batch,
            saturation_qps_list=args.saturation_qps_list,
            saturation_restarts_list=args.saturation_restarts_list,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
