"""Single-tier execution and cleanup logic."""

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from .certs import create_cert_secret, generate_certs

from .config import (
    DEFAULT_NODEPOOL, FAKE_EXPORTER_ROLES, KONN_AGENT_IMAGE,
    KONN_SERVER_IMAGE, PODS_PER_NODE, REAL_TARGET_ROLES, VMAGENT_IMAGE,
    VMSINGLE_IMAGE, log,
)
from .deploy import (
    deploy_fake_exporters, deploy_konnectivity_agents,
    deploy_konnectivity_server, deploy_vmagent, deploy_vmsingle,
    ensure_namespace, get_dp_api_server, get_node_ips, get_server_lb_ip,
    rollout_restart, setup_dp_access,
)
from .metrics import collect_metrics, collect_pprof, evaluate_pass_fail, wait_for_targets
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
        total_targets = len(node_ips) * len(REAL_TARGET_ROLES)
        log.info("")
        log.info("=" * 60)
        log.info("TIER: %d nodes (real targets) — %d nodes × %d roles = %d targets",
                 tier, len(node_ips), len(REAL_TARGET_ROLES), total_targets)
        log.info("=" * 60)
    else:
        total_targets = tier * len(FAKE_EXPORTER_ROLES)
        # pods per tier: 4 exporter roles × tier replicas + tier konn-agents
        pods_needed = tier * (len(FAKE_EXPORTER_ROLES) + 1)
        nodes_needed = math.ceil(pods_needed / PODS_PER_NODE)
        if resource_group and dp_cluster_name:
            log.info("Tier %d needs %d pods → scaling DP to %d nodes",
                     tier, pods_needed, nodes_needed)
            scale_dp_nodepool(resource_group, dp_cluster_name, nodepool, nodes_needed)
            wait_for_nodes_ready(dp_kubeconfig, expected=nodes_needed, timeout_minutes=30)
        log.info("")
        log.info("=" * 60)
        log.info("TIER: %d replicas × %d roles = %d targets (%d pods, %d nodes)",
                 tier, len(FAKE_EXPORTER_ROLES), total_targets, pods_needed, nodes_needed)
        log.info("=" * 60)

    # 1. Create namespaces
    ensure_namespace(cp_kubeconfig, namespace)
    ensure_namespace(dp_kubeconfig, namespace)

    # 2. Deploy konnectivity server (skip wait — needs certs, will crashloop)
    deploy_konnectivity_server(cp_kubeconfig, namespace, server_count=1, wait=False)

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

    # 10. Wait for targets to come up (polls every 30s, samples resource usage)
    log.info("Waiting for %d targets (timeout %dm)...", total_targets, warm_up_minutes)
    _up, _total, resource_samples = wait_for_targets(
        cp_kubeconfig, dp_kubeconfig, namespace,
        expected=total_targets, timeout_minutes=warm_up_minutes)
    log.info("Target readiness check complete.")

    # 11. Collect metrics
    measurements = collect_metrics(cp_kubeconfig, dp_kubeconfig, namespace, tier, work_dir)

    # 11b. Collect pprof profiles from konn-server, konn-agent, and vmagent
    pprof_results = collect_pprof(cp_kubeconfig, dp_kubeconfig, namespace, work_dir, label=f"tier{tier}")

    # 12. Evaluate pass/fail
    pass_fail = evaluate_pass_fail(measurements)
    if pass_fail["overall"]:
        log.info("RESULT: PASS")
    else:
        log.info("RESULT: FAIL")

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
        "pass_criteria": pass_fail,
        "pass": pass_fail["overall"],
        "status": "completed",
    }

    label_suffix = f"-{run_label}" if run_label else ""
    results_file = results_dir / f"fake-cp-loadtest-{run_id}{label_suffix}-{tier}.json"
    results_file.write_text(json.dumps(result, indent=2))
    log.info("Tier %d results: %s", tier, results_file)

    return result


def cleanup_tier(cp_kubeconfig: str, dp_kubeconfig: str, tier: int,
                 run_label: str = "") -> None:
    """Clean up a single tier's namespaces before retrying."""
    ns_prefix = f"loadtest-{run_label}-" if run_label else "loadtest-"
    namespace = f"{ns_prefix}{tier}"
    log.info("Cleaning up tier %d namespace: %s", tier, namespace)
    for kubeconfig, label in [(cp_kubeconfig, "CP"), (dp_kubeconfig, "DP")]:
        kubectl(kubeconfig, "delete", "ns", namespace, "--wait=true",
                "--timeout=120s", check=False)
    # Wait for namespace termination
    for kubeconfig in [cp_kubeconfig, dp_kubeconfig]:
        for _ in range(60):
            result = kubectl(kubeconfig, "get", "ns", namespace, check=False)
            if result.returncode != 0:
                break
            time.sleep(5)
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
