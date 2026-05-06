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
import threading
from datetime import datetime, timezone

from clusterloader2.utils import parse_xml_to_json, run_cl2_command, process_cl2_reports


def configure_clusterloader2(
    namespaces,
    deployments_per_namespace,
    replicas_per_deployment,
    operation_timeout,
    override_file,
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
        f.write("CL2_PROMETHEUS_MEMORY_LIMIT: 2Gi\n")
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

    with open(override_file, "r", encoding="utf-8") as f:
        print(f"Content of file {override_file}:\n{f.read()}")


def execute_clusterloader2(
    cl2_image,
    cl2_config_dir,
    cl2_report_dir,
    cl2_config_file,
    kubeconfig,
    provider,
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
        tear_down_prometheus=False,
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
    proc = subprocess.Popen(
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
    }
    content = process_cl2_reports(cl2_report_dir, template)

    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(content)


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

    # execute
    pe = subparsers.add_parser("execute", help="Run CL2 against a single cluster")
    pe.add_argument("--cl2-image", type=str, required=True)
    pe.add_argument("--cl2-config-dir", type=str, required=True)
    pe.add_argument("--cl2-report-dir", type=str, required=True)
    pe.add_argument("--cl2-config-file", type=str, required=True)
    pe.add_argument("--kubeconfig", type=str, required=True)
    pe.add_argument("--provider", type=str, required=True)

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

    args = parser.parse_args()

    if args.command == "configure":
        configure_clusterloader2(
            args.namespaces,
            args.deployments_per_namespace,
            args.replicas_per_deployment,
            args.operation_timeout,
            args.cl2_override_file,
        )
    elif args.command == "execute":
        execute_clusterloader2(
            args.cl2_image,
            args.cl2_config_dir,
            args.cl2_report_dir,
            args.cl2_config_file,
            args.kubeconfig,
            args.provider,
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
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
