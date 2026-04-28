"""Single-tier execution and cleanup logic."""

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .certs import create_cert_secret, generate_certs

from .config import (
    AGENT_CPU_REQUEST, DAEMONSET_POD_TARGET_ROLES,
    DAEMONSET_TARGET_ROLES, DEFAULT_NODEPOOL, EXPORTER_CPU_REQUEST,
    FAKE_EXPORTER_ROLES, KONN_AGENT_IMAGE,
    KONN_SERVER_IMAGE, NODE_ALLOCATABLE_CPU, PODS_PER_NODE,
    REAL_TARGET_ROLES, SINGLETON_POD_TARGET_ROLES,
    SYSTEM_CPU_PER_NODE, VMAGENT_IMAGE,
    VMSINGLE_IMAGE, log,
)
from .deploy import (
    deploy_fake_exporters, deploy_konnectivity_agents,
    deploy_konnectivity_server, deploy_vmagent, deploy_vmsingle,
    ensure_namespace, get_dp_api_server, get_node_ips, get_server_lb_ip,
    rollout_restart, setup_dp_access,
)
from .adx import (
    export_if_configured as adx_export_if_configured,
    export_summary_if_configured as adx_export_summary_if_configured,
)
from .metrics import collect_diagnostics, collect_metrics, collect_pprof, evaluate_pass_fail, wait_for_targets
from .scaling import scale_dp_nodepool, wait_for_nodes_ready
from .utils import kubectl


def run_single_tier(cp_kubeconfig: str, dp_kubeconfig: str, tier: int,
                    warm_up_minutes: int,
                    work_dir: Path, results_dir: Path, run_id: str,
                    real_targets: bool = False,
                    resource_group: str = "", dp_cluster_name: str = "",
                    nodepool: str = DEFAULT_NODEPOOL,
                    run_label: str = "") -> dict:
    ns_prefix = f"loadtest-{run_label}-" if run_label else "loadtest-"
    namespace = f"{ns_prefix}{tier}"

    if real_targets:
        if resource_group and dp_cluster_name:
            scale_dp_nodepool(resource_group, dp_cluster_name, nodepool, tier)
            wait_for_nodes_ready(dp_kubeconfig, expected=tier, timeout_minutes=30)

        node_ips = get_node_ips(dp_kubeconfig)
        dp_nodes = len(node_ips)
        per_node_roles = (len(REAL_TARGET_ROLES)
                         + len(DAEMONSET_TARGET_ROLES)
                         + len(DAEMONSET_POD_TARGET_ROLES))
        singleton_roles = len(SINGLETON_POD_TARGET_ROLES)
        min_targets = dp_nodes * per_node_roles + singleton_roles
        log.info("")
        log.info("=" * 60)
        log.info("TIER: %d nodes (real targets) — min %d targets "
                 "(%d nodes × %d roles + %d singletons)",
                 tier, min_targets, dp_nodes, per_node_roles, singleton_roles)
        log.info("=" * 60)
    else:
        min_targets = tier * len(FAKE_EXPORTER_ROLES)
        # pods per tier: 4 exporter roles × tier replicas + tier konn-agents
        pods_needed = tier * (len(FAKE_EXPORTER_ROLES) + 1)
        nodes_by_pods = math.ceil(pods_needed / PODS_PER_NODE)
        # CPU requests: exporters + agents + system overhead
        total_cpu = (tier * len(FAKE_EXPORTER_ROLES) * EXPORTER_CPU_REQUEST
                     + tier * AGENT_CPU_REQUEST)
        usable_cpu_per_node = NODE_ALLOCATABLE_CPU - SYSTEM_CPU_PER_NODE
        nodes_by_cpu = math.ceil(total_cpu / usable_cpu_per_node)
        nodes_needed = max(nodes_by_pods, nodes_by_cpu)
        if resource_group and dp_cluster_name:
            log.info("Tier %d needs %d pods (→%d nodes) / %dm CPU (→%d nodes) → scaling DP to %d nodes",
                     tier, pods_needed, nodes_by_pods, total_cpu, nodes_by_cpu, nodes_needed)
            scale_dp_nodepool(resource_group, dp_cluster_name, nodepool, nodes_needed)
            wait_for_nodes_ready(dp_kubeconfig, expected=nodes_needed, timeout_minutes=30)
        log.info("")
        log.info("=" * 60)
        log.info("TIER: %d replicas × %d roles = min %d targets (%d pods, %d nodes)",
                 tier, len(FAKE_EXPORTER_ROLES), min_targets, pods_needed, nodes_needed)
        log.info("  (DaemonSet targets will be auto-discovered)")
        log.info("=" * 60)

    # 1. Create namespaces
    ensure_namespace(cp_kubeconfig, namespace)
    ensure_namespace(dp_kubeconfig, namespace)

    # 2. Deploy konnectivity server (skip wait — needs certs, will crashloop)
    #    Scale replicas: 1 per 150 agents to distribute tunnel/TLS load
    server_count = max(1, (tier + 149) // 150)
    log.info("Konnectivity server replicas: %d (tier %d)", server_count, tier)
    deploy_konnectivity_server(cp_kubeconfig, namespace, server_count=server_count, wait=False)

    # 3. Get LB IP
    server_ip = get_server_lb_ip(cp_kubeconfig, namespace)
    log.info("Konnectivity server LB IP: %s", server_ip)

    # 4. Generate certs with LB IP as SAN
    cert_dir = generate_certs(work_dir / "certs" / namespace, namespace, server_ip)

    # 5. Create cert secrets on both clusters
    create_cert_secret(cp_kubeconfig, namespace, cert_dir)
    create_cert_secret(dp_kubeconfig, namespace, cert_dir)

    # 6. Restart server with certs
    rollout_restart(cp_kubeconfig, namespace, "deployment/konnectivity-server")
    log.info("Konnectivity server ready with certs")

    # 7. Deploy fake exporters (4 roles × tier replicas) — skip for real targets
    if not real_targets:
        deploy_fake_exporters(dp_kubeconfig, tier)

    # 8. Deploy agents + restart to pick up certs
    deploy_konnectivity_agents(dp_kubeconfig, namespace, server_ip, tier)
    rollout_restart(dp_kubeconfig, namespace, "deployment/konnectivity-agent")

    # 8b. Set up RBAC and token for kubernetes_sd_configs + kubelet scraping
    setup_dp_access(dp_kubeconfig, cp_kubeconfig, namespace)
    dp_api_server = get_dp_api_server(dp_kubeconfig)

    # 9. Deploy vmsingle receiver, then VMAgent (SD discovers targets dynamically)
    deploy_vmsingle(cp_kubeconfig, namespace)
    deploy_vmagent(cp_kubeconfig, namespace, dp_api_server)
    tier_start_ts = time.time()  # ADX time-series window starts here

    # 10. Wait for targets to come up (polls every 30s, samples resource usage)
    log.info("Waiting for targets (min %d, timeout %dm)...", min_targets, warm_up_minutes)
    _up, _total, resource_samples = wait_for_targets(
        cp_kubeconfig, dp_kubeconfig, namespace,
        expected=min_targets, timeout_minutes=warm_up_minutes)
    log.info("Target readiness check complete.")

    # 11. Collect metrics
    measurements = {}
    pprof_results = {}
    diagnostics = {}
    pass_fail = {}
    try:
        measurements = collect_metrics(cp_kubeconfig, dp_kubeconfig, namespace, tier, work_dir)

        # 11b. Brief pause to let port-forward ports fully release before pprof
        time.sleep(5)

        # 11c. Collect pprof profiles from konn-server, konn-agent, and vmagent
        pprof_results = collect_pprof(cp_kubeconfig, dp_kubeconfig, namespace, work_dir, label=f"tier{tier}")

        # 12. Evaluate pass/fail
        pass_fail = evaluate_pass_fail(measurements, expected_targets=min_targets)
        if pass_fail["overall"] == "success":
            log.info("RESULT: success")
        else:
            log.info("RESULT: failure")

        # 12b. Push time-series to ADX (no-op unless ADX_CLUSTER_URI/ADX_DATABASE set)
        adx_export_if_configured(
            cp_kubeconfig, namespace, run_id, tier,
            mode="real-targets" if real_targets else "fake-targets",
            start_ts=tier_start_ts,
        )

        # 12c. Push per-tier summary row to ADX (additive)
        adx_export_summary_if_configured(
            run_id=run_id,
            tier=tier,
            mode="real-targets" if real_targets else "fake-targets",
            result=pass_fail.get("overall", "failure"),
            measurements=measurements,
            pass_criteria=pass_fail,
        )
    finally:
        # Always collect diagnostics (logs, events, pod descriptions) for RCA
        try:
            diagnostics = collect_diagnostics(
                cp_kubeconfig, dp_kubeconfig, namespace, work_dir,
                include_fake_exporters=not real_targets)
        except Exception as e:
            log.warning("Diagnostics collection failed: %s", e)

    # 13. Write results
    results_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tier": tier,
        "namespace": namespace,
        "mode": "real-targets" if real_targets else "fake-targets",
        "dp_node_count": len(get_node_ips(dp_kubeconfig)) if real_targets else None,
        "config": {
            "warm_up_minutes": warm_up_minutes,
            "konn_server_image": KONN_SERVER_IMAGE,
            "konn_agent_image": KONN_AGENT_IMAGE,
            "vmagent_image": VMAGENT_IMAGE,
            "vmsingle_image": VMSINGLE_IMAGE,
        },
        "measurements": measurements,
        "resource_samples": resource_samples,
        "pprof": pprof_results,
        "diagnostics": diagnostics,
        "pass_criteria": pass_fail,
        "result": pass_fail.get("overall", "failure"),
        "status": "completed",
    }

    label_suffix = f"-{run_label}" if run_label else ""
    results_file = results_dir / f"vmagent-loadtest-{run_id}{label_suffix}-{tier}.json"
    results_file.write_text(json.dumps(result, indent=2))
    log.info("Tier %d results: %s", tier, results_file)

    # Export resource_samples as standalone CSV for easier analysis
    if resource_samples:
        import csv
        csv_file = results_dir / f"resource-usage-tier{tier}.csv"
        fieldnames = sorted({k for s in resource_samples for k in s.keys()})
        with open(csv_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(resource_samples)
        log.info("Resource usage CSV: %s", csv_file)

    return result


def _wait_ns_gone(kubeconfig: str, namespace: str, timeout: int = 300) -> None:
    """Delete namespace and wait for it to disappear."""
    kubectl(kubeconfig, "delete", "ns", namespace, "--wait=false", check=False)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = kubectl(kubeconfig, "get", "ns", namespace, check=False)
        if result.returncode != 0:
            return
        time.sleep(5)
    log.warning("Namespace %s still terminating after %ds", namespace, timeout)


def cleanup_tier(cp_kubeconfig: str, dp_kubeconfig: str, tier: int,
                 run_label: str = "") -> None:
    """Clean up a single tier's namespaces (CP + DP in parallel)."""
    ns_prefix = f"loadtest-{run_label}-" if run_label else "loadtest-"
    namespace = f"{ns_prefix}{tier}"
    log.info("Cleaning up tier %d namespace: %s", tier, namespace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(_wait_ns_gone, cp_kubeconfig, namespace)
        pool.submit(_wait_ns_gone, dp_kubeconfig, namespace)
    log.info("Tier %d cleanup complete.", tier)


def cleanup(cp_kubeconfig: str, dp_kubeconfig: str) -> None:
    log.info("Cleaning up loadtest namespaces...")
    for kubeconfig, label in [(cp_kubeconfig, "CP"), (dp_kubeconfig, "DP")]:
        result = kubectl(
            kubeconfig, "get", "ns", "-l", "loadtest=true",
            "-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}",
            check=False,
        )
        for ns in result.stdout.strip().split("\n"):
            ns = ns.strip()
            if ns:
                log.info("  Deleting %s namespace: %s", label, ns)
                kubectl(kubeconfig, "delete", "ns", ns, "--wait=false", check=False)
    log.info("Cleanup complete.")
