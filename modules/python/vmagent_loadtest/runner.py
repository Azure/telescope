"""Single-tier execution and cleanup logic."""

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .certs import create_cert_secret, generate_certs

from .config import (
    AGENT_CPU_REQUEST, AGENT_MEM_REQUEST_MI, DAEMONSET_POD_TARGET_ROLES,
    DAEMONSET_TARGET_ROLES, DEFAULT_NODEPOOL, EXPORTER_CPU_REQUEST,
    EXPORTER_MEM_REQUEST_MI, FAKE_EXPORTER_ROLES, KONN_AGENT_IMAGE,
    KONN_SERVER_IMAGE, NODE_ALLOCATABLE_CPU, NODE_ALLOCATABLE_MEM_MI,
    PODS_PER_NODE, REAL_TARGET_ROLES, SINGLETON_POD_TARGET_ROLES,
    SYSTEM_CPU_PER_NODE, SYSTEM_MEM_PER_NODE_MI, VMAGENT_IMAGE,
    VMAGENT_PROXY_IMAGE, VMAGENT_FLUSH_INTERVAL, VMAGENT_RATE_LIMIT,
    VMSINGLE_IMAGE, compute_resources_for_tier, compute_shard_count,
    konnectivity_agent_replicas_for_node_count, log,
)
from .deploy import (
    deploy_fake_exporters, deploy_konnectivity_agents,
    deploy_konnectivity_server, deploy_vmagent, deploy_vmsingle,
    ensure_namespace, get_dp_api_server, get_node_ips, get_server_lb_ip,
    rollout_restart, scale_fake_exporters, setup_dp_access,
    wait_for_fake_exporters_gone,
)
from .adx import (
    export_if_configured as adx_export_if_configured,
    export_summary_if_configured as adx_export_summary_if_configured,
    collect_resource_peaks as adx_collect_resource_peaks,
)
from .metrics import (
    collect_diagnostics, collect_metrics, collect_pprof, dwell_and_sample,
    evaluate_pass_fail, observe_remotewrite_drain, wait_for_targets,
)
from .scaling import scale_dp_nodepool, wait_for_nodes_ready
from .utils import kubectl


def _flush_interval_seconds(flush_interval: str) -> int:
    """Parse a Go duration string like '30s', '1m', '500ms' into whole seconds.

    Only handles the simple single-unit forms vmagent's -remoteWrite.flushInterval
    actually takes in this harness (e.g. '1s', '30s', '1m'); falls back to 30
    (prod's current default) if parsing fails.
    """
    try:
        s = flush_interval.strip()
        if s.endswith("ms"):
            return max(1, round(int(s[:-2]) / 1000))
        if s.endswith("s"):
            return int(s[:-1])
        if s.endswith("m"):
            return int(s[:-1]) * 60
        return int(s)
    except (ValueError, AttributeError):
        return 30


def compute_fake_nodes_needed(tier: int) -> int:
    """Return DP node count needed to host one fake-mode tier of size `tier`.

    Used by both the per-tier sequential path (scales DP to this number) and
    the parallel orchestrator (pre-sizes DP to the SUM across all tiers).
    """
    pods_needed = tier * (len(FAKE_EXPORTER_ROLES) + 1)
    nodes_by_pods = math.ceil(pods_needed / PODS_PER_NODE)
    total_cpu = (tier * len(FAKE_EXPORTER_ROLES) * EXPORTER_CPU_REQUEST
                 + tier * AGENT_CPU_REQUEST)
    usable_cpu_per_node = NODE_ALLOCATABLE_CPU - SYSTEM_CPU_PER_NODE
    nodes_by_cpu = math.ceil(total_cpu / usable_cpu_per_node)
    # Memory packing dominates at higher tiers: fake-exporter requests 16Mi,
    # konn-agent requests 64Mi; nodes saturate by memory well before CPU.
    total_mem = (tier * len(FAKE_EXPORTER_ROLES) * EXPORTER_MEM_REQUEST_MI
                 + tier * AGENT_MEM_REQUEST_MI)
    usable_mem_per_node = NODE_ALLOCATABLE_MEM_MI - SYSTEM_MEM_PER_NODE_MI
    nodes_by_mem = math.ceil(total_mem / usable_mem_per_node)
    # Apply 15% headroom so scheduler isn't packing at 99%.
    return math.ceil(max(nodes_by_pods, nodes_by_cpu, nodes_by_mem) * 1.15)


def run_single_tier(cp_kubeconfig: str, dp_kubeconfig: str, tier: int,
                    warm_up_minutes: int,
                    work_dir: Path, results_dir: Path, run_id: str,
                    real_targets: bool = False,
                    resource_group: str = "", dp_cluster_name: str = "",
                    nodepool: str = DEFAULT_NODEPOOL,
                    run_label: str = "",
                    skip_diagnostics: bool = True,
                    rate_limit: int = VMAGENT_RATE_LIMIT,
                    max_block_size: int = 8388608,
                    queues: int = 8,
                    max_rows_per_block: int = 10000,
                    measure_drain: bool = False,
                    drain_observe_seconds: int = 120,
                    konn_server_image: str = KONN_SERVER_IMAGE,
                    konn_agent_image: str = KONN_AGENT_IMAGE) -> dict:
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
        min_targets = int(tier * len(FAKE_EXPORTER_ROLES) * 0.95)
        # pods per tier: 4 exporter roles × tier replicas + tier konn-agents
        pods_needed = tier * (len(FAKE_EXPORTER_ROLES) + 1)
        total_cpu = (tier * len(FAKE_EXPORTER_ROLES) * EXPORTER_CPU_REQUEST
                     + tier * AGENT_CPU_REQUEST)
        nodes_needed = compute_fake_nodes_needed(tier)
        if resource_group and dp_cluster_name:
            log.info("Tier %d needs %d pods / %dm CPU → scaling DP to %d nodes",
                     tier, pods_needed, total_cpu, nodes_needed)
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
    #    Scale replicas: ~1 per 750 proxied targets to distribute CONNECT/tunnel
    #    load. konn-server measured at ~0.18 cores even at tier 1000 (idle), so
    #    1-per-500 over-provisioned the pod count and pressured the CP nodepool.
    #    Proxied targets ≈ tier × fake-roles + tier agents + ~50 real proxied.
    proxied_targets = tier * len(FAKE_EXPORTER_ROLES) + tier + 50
    server_count = max(3, (proxied_targets + 1999) // 2000)
    tier_resources = compute_resources_for_tier(tier)
    shard_count = compute_shard_count(tier)
    log.info("Konnectivity server replicas: %d (tier %d, proxied≈%d)",
             server_count, tier, proxied_targets)
    log.info("VMAgent shards: %d (≈%d targets/shard)",
             shard_count, (tier * len(FAKE_EXPORTER_ROLES)) // shard_count)
    log.info("Tier %d per-shard resources: vmagent=%s/%s (lim %s/%s), proxy=%s/%s (lim %s/%s), "
             "konn-server=%s/%s (lim %s/%s)",
             tier,
             tier_resources["vmagent"]["cpu_req"], tier_resources["vmagent"]["mem_req"],
             tier_resources["vmagent"]["cpu_lim"], tier_resources["vmagent"]["mem_lim"],
             tier_resources["vmagent_proxy"]["cpu_req"], tier_resources["vmagent_proxy"]["mem_req"],
             tier_resources["vmagent_proxy"]["cpu_lim"], tier_resources["vmagent_proxy"]["mem_lim"],
             tier_resources["konn_server"]["cpu_req"], tier_resources["konn_server"]["mem_req"],
             tier_resources["konn_server"]["cpu_lim"], tier_resources["konn_server"]["mem_lim"])
    deploy_konnectivity_server(cp_kubeconfig, namespace, server_count=server_count,
                                resources=tier_resources["konn_server"], wait=False,
                                server_image=konn_server_image)

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
    node_count_for_agents = dp_nodes if real_targets else nodes_needed
    agent_replica_count = konnectivity_agent_replicas_for_node_count(node_count_for_agents)
    deploy_konnectivity_agents(dp_kubeconfig, namespace, server_ip, agent_replica_count,
                                agent_image=konn_agent_image)
    rollout_restart(dp_kubeconfig, namespace, "deployment/konnectivity-agent")

    # 8b. Set up RBAC and token for kubernetes_sd_configs + kubelet scraping
    setup_dp_access(dp_kubeconfig, cp_kubeconfig, namespace)
    dp_api_server = get_dp_api_server(dp_kubeconfig)

    # 9. Deploy vmsingle receiver, then VMAgent (SD discovers targets dynamically)
    deploy_vmsingle(cp_kubeconfig, namespace)
    deploy_vmagent(cp_kubeconfig, namespace, dp_api_server,
                   vmagent_resources=tier_resources["vmagent"],
                   proxy_resources=tier_resources["vmagent_proxy"],
                   replicas=shard_count,
                   rate_limit=rate_limit,
                   max_block_size=max_block_size,
                   queues=queues,
                   max_rows_per_block=max_rows_per_block)
    tier_start_ts = time.time()  # ADX time-series window starts here
    wall_start_ts = tier_start_ts

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

        # 11a. Optionally observe remote-write backlog drain over a fixed
        # window (opt-in; tests whether a preStop-hook-style delay before
        # SIGTERM would actually shrink the persistent queue under this
        # rateLimit/maxBlockSize/flushInterval config). For fake-targets runs,
        # scrape generation is paused first so this measures genuine drain
        # rate against the *existing* backlog -- mirroring what happens on
        # SIGTERM, when promscrape's scrape loops are canceled and only the
        # remote-write drain continues -- rather than conflating it with
        # "can drain keep up with sustained arrivals" (a different question).
        if measure_drain:
            paused_exporters = False
            if not real_targets:
                try:
                    scale_fake_exporters(dp_kubeconfig, 0)
                    wait_for_fake_exporters_gone(dp_kubeconfig)
                    # Let any in-flight scrapes/blocks still forming settle:
                    # at least one flush_interval plus a fixed buffer.
                    settle_seconds = max(35, _flush_interval_seconds(VMAGENT_FLUSH_INTERVAL) + 15)
                    log.info("Settling %ds after pausing exporters before drain observation...",
                             settle_seconds)
                    time.sleep(settle_seconds)
                    paused_exporters = True
                except Exception as e:
                    log.warning("Failed to pause fake exporters before drain observation "
                               "(will measure with targets still live): %s", e)
            log.info("Observing remote-write drain for %ds...", drain_observe_seconds)
            try:
                drain_stats = observe_remotewrite_drain(
                    cp_kubeconfig, namespace, work_dir,
                    duration_seconds=drain_observe_seconds)
                measurements.update(drain_stats)
                measurements["remotewrite_drain_exporters_paused"] = paused_exporters
                log.info("Drain observation: initial=%.0fB final=%.0fB reduced=%.1f%% "
                         "seconds_to_empty=%s exporters_paused=%s",
                         drain_stats["remotewrite_drain_initial_bytes"],
                         drain_stats["remotewrite_drain_final_bytes"],
                         drain_stats["remotewrite_drain_pct_reduced"],
                         drain_stats["remotewrite_drain_seconds_to_empty"],
                         paused_exporters)
            finally:
                if paused_exporters:
                    try:
                        scale_fake_exporters(dp_kubeconfig, tier)
                    except Exception as e:
                        log.warning("Failed to resume fake exporters after drain "
                                   "observation: %s", e)

        # 11b. Brief pause to let port-forward ports fully release before pprof
        time.sleep(5)

        # 11c. Collect pprof profiles from konn-server, konn-agent, and vmagent
        if skip_diagnostics:
            log.info("Skipping pprof collection (--skip-diagnostics)")
        else:
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

        # 12c. Collect peak resource usage for the summary row (cheap PromQL).
        peaks = adx_collect_resource_peaks(cp_kubeconfig, namespace, tier_start_ts)
        measurements.update(peaks)

        # 12d. Push per-tier summary row to ADX (additive)
        try:
            agent_replicas = agent_replica_count
            vmagent_replicas = shard_count
            dp_node_count = (len(get_node_ips(dp_kubeconfig))
                             if real_targets else compute_fake_nodes_needed(tier))
        except Exception:
            agent_replicas = agent_replica_count
            vmagent_replicas = shard_count
            dp_node_count = 0

        adx_export_summary_if_configured(
            run_id=run_id,
            tier=tier,
            mode="real-targets" if real_targets else "fake-targets",
            result=pass_fail.get("overall", "failure"),
            measurements=measurements,
            pass_criteria=pass_fail,
            run_label=run_label or "",
            trial_label="",
            wall_time_seconds=time.time() - wall_start_ts,
            dp_node_count=dp_node_count,
            konn_server_replicas=server_count,
            konn_agent_replicas=agent_replicas,
            vmagent_replicas=vmagent_replicas,
            config={
                "warm_up_minutes": warm_up_minutes,
                "rate_limit": rate_limit,
                "max_block_size": max_block_size,
                "flush_interval": VMAGENT_FLUSH_INTERVAL,
                "queues": queues,
                "max_rows_per_block": max_rows_per_block,
                "konn_server_image": konn_server_image,
                "konn_agent_image": konn_agent_image,
                "vmagent_image": VMAGENT_IMAGE,
                "vmagent_proxy_image": VMAGENT_PROXY_IMAGE,
                "enable_tunnel_reuse": True,
                "vmsingle_image": VMSINGLE_IMAGE,
                "nodepool": nodepool,
            },
        )
    finally:
        # Always collect diagnostics (logs, events, pod descriptions) for RCA
        if skip_diagnostics:
            log.info("Skipping diagnostics collection (--skip-diagnostics)")
        else:
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
            "rate_limit": rate_limit,
            "max_block_size": max_block_size,
            "flush_interval": VMAGENT_FLUSH_INTERVAL,
            "queues": queues,
            "max_rows_per_block": max_rows_per_block,
            "konn_server_image": konn_server_image,
            "konn_agent_image": konn_agent_image,
            "vmagent_image": VMAGENT_IMAGE,
            "vmagent_proxy_image": VMAGENT_PROXY_IMAGE,
            "enable_tunnel_reuse": True,
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


def run_real_targets_ramp(cp_kubeconfig: str, dp_kubeconfig: str, tiers: list[int],
                          warm_up_minutes: int,
                          work_dir: Path, results_dir: Path, run_id: str,
                          resource_group: str, dp_cluster_name: str,
                          nodepool: str = DEFAULT_NODEPOOL,
                          run_label: str = "",
                          skip_diagnostics: bool = True,
                          rate_limit: int = VMAGENT_RATE_LIMIT,
                          max_block_size: int = 8388608,
                          queues: int = 8,
                          max_rows_per_block: int = 10000,
                          konn_server_image: str = KONN_SERVER_IMAGE,
                          konn_agent_image: str = KONN_AGENT_IMAGE) -> dict:
    """Ramp the DP nodepool through every node count in `tiers` (ascending)
    inside ONE continuous namespace/deployment, mirroring how a real prod
    cluster is actually scaled up (e.g. 0->400->800->...->2000) and watched
    the whole way -- instead of tearing down and redeploying a fresh stack
    per checkpoint. At each step: scale the nodepool, reconcile
    konnectivity-server/vmagent sizing for the new node count (idempotent
    applies), then dwell for `warm_up_minutes` sampling CPU/memory/
    restarts/OOMs/scrape health every 30s so the climb toward the target is
    visible the whole way, not just in a final snapshot.
    """
    steps = sorted(set(tiers))
    namespace = f"loadtest-{run_label}-ramp" if run_label else "loadtest-ramp"

    log.info("")
    log.info("=" * 60)
    log.info("REAL-TARGETS RAMP: %d -> %d nodes (%d steps: %s)",
             steps[0], steps[-1], len(steps), steps)
    log.info("=" * 60)

    def _reconcile_cp_stack(tier: int) -> tuple[int, int, dict]:
        proxied_targets = tier * len(FAKE_EXPORTER_ROLES) + tier + 50
        server_count = max(3, (proxied_targets + 1999) // 2000)
        return server_count, compute_shard_count(tier), compute_resources_for_tier(tier)

    # 1. Create namespaces (once for the whole ramp)
    ensure_namespace(cp_kubeconfig, namespace)
    ensure_namespace(dp_kubeconfig, namespace)

    # 2. Deploy konnectivity server sized for the first (smallest) step
    first_tier = steps[0]
    server_count, shard_count, tier_resources = _reconcile_cp_stack(first_tier)
    deploy_konnectivity_server(cp_kubeconfig, namespace, server_count=server_count,
                                resources=tier_resources["konn_server"], wait=False,
                                server_image=konn_server_image)
    server_ip = get_server_lb_ip(cp_kubeconfig, namespace)
    log.info("Konnectivity server LB IP: %s", server_ip)
    cert_dir = generate_certs(work_dir / "certs" / namespace, namespace, server_ip)
    create_cert_secret(cp_kubeconfig, namespace, cert_dir)
    create_cert_secret(dp_kubeconfig, namespace, cert_dir)
    rollout_restart(cp_kubeconfig, namespace, "deployment/konnectivity-server")

    deploy_konnectivity_agents(dp_kubeconfig, namespace, server_ip,
                                konnectivity_agent_replicas_for_node_count(first_tier),
                                agent_image=konn_agent_image)
    rollout_restart(dp_kubeconfig, namespace, "deployment/konnectivity-agent")

    setup_dp_access(dp_kubeconfig, cp_kubeconfig, namespace)
    dp_api_server = get_dp_api_server(dp_kubeconfig)

    deploy_vmsingle(cp_kubeconfig, namespace)
    deploy_vmagent(cp_kubeconfig, namespace, dp_api_server,
                   vmagent_resources=tier_resources["vmagent"],
                   proxy_resources=tier_resources["vmagent_proxy"],
                   replicas=shard_count,
                   rate_limit=rate_limit,
                   max_block_size=max_block_size,
                   queues=queues,
                   max_rows_per_block=max_rows_per_block)
    ramp_start_ts = time.time()

    all_samples: list[dict] = []
    step_results: list[dict] = []

    for tier in steps:
        log.info("")
        log.info("-" * 60)
        log.info("RAMP STEP: scaling DP nodepool to %d nodes", tier)
        log.info("-" * 60)
        step_start_ts = time.time()

        scale_dp_nodepool(resource_group, dp_cluster_name, nodepool, tier)
        wait_for_nodes_ready(dp_kubeconfig, expected=tier, timeout_minutes=30)

        # Reconcile CP-side sizing for the new node count (idempotent applies)
        server_count, shard_count, tier_resources = _reconcile_cp_stack(tier)
        deploy_konnectivity_server(cp_kubeconfig, namespace, server_count=server_count,
                                    resources=tier_resources["konn_server"], wait=True,
                                    server_image=konn_server_image)
        agent_replica_count = konnectivity_agent_replicas_for_node_count(tier)
        deploy_konnectivity_agents(dp_kubeconfig, namespace, server_ip, agent_replica_count,
                                    agent_image=konn_agent_image)
        deploy_vmagent(cp_kubeconfig, namespace, dp_api_server,
                       vmagent_resources=tier_resources["vmagent"],
                       proxy_resources=tier_resources["vmagent_proxy"],
                       replicas=shard_count,
                       rate_limit=rate_limit,
                       max_block_size=max_block_size,
                       queues=queues,
                       max_rows_per_block=max_rows_per_block)

        node_ips = get_node_ips(dp_kubeconfig)
        dp_nodes = len(node_ips)
        per_node_roles = (len(REAL_TARGET_ROLES)
                         + len(DAEMONSET_TARGET_ROLES)
                         + len(DAEMONSET_POD_TARGET_ROLES))
        singleton_roles = len(SINGLETON_POD_TARGET_ROLES)
        min_targets = dp_nodes * per_node_roles + singleton_roles

        log.info("Dwelling %dm at %d nodes (sampling every 30s)...", warm_up_minutes, tier)
        step_samples = dwell_and_sample(cp_kubeconfig, dp_kubeconfig, namespace,
                                        node_count=tier, duration_minutes=warm_up_minutes)
        all_samples.extend(step_samples)
        last_sample = step_samples[-1] if step_samples else {}

        step_measurements = collect_metrics(cp_kubeconfig, dp_kubeconfig, namespace, tier, work_dir)
        step_pass_fail = evaluate_pass_fail(step_measurements, expected_targets=min_targets)
        # Push this step's time series to ADX (no-op unless ADX_CLUSTER_URI/ADX_DATABASE set)
        adx_export_if_configured(cp_kubeconfig, namespace, run_id, tier,
                                  mode="real-targets", start_ts=step_start_ts)
        step_measurements.update(adx_collect_resource_peaks(cp_kubeconfig, namespace, ramp_start_ts))

        adx_export_summary_if_configured(
            run_id=run_id,
            tier=tier,
            mode="real-targets",
            result=step_pass_fail.get("overall", "failure"),
            measurements=step_measurements,
            pass_criteria=step_pass_fail,
            run_label=run_label or "",
            trial_label=f"ramp-step-{tier}",
            wall_time_seconds=time.time() - ramp_start_ts,
            dp_node_count=dp_nodes,
            konn_server_replicas=server_count,
            konn_agent_replicas=agent_replica_count,
            vmagent_replicas=shard_count,
            config={
                "warm_up_minutes": warm_up_minutes,
                "rate_limit": rate_limit,
                "max_block_size": max_block_size,
                "flush_interval": VMAGENT_FLUSH_INTERVAL,
                "queues": queues,
                "max_rows_per_block": max_rows_per_block,
                "konn_server_image": konn_server_image,
                "konn_agent_image": konn_agent_image,
                "vmagent_image": VMAGENT_IMAGE,
                "vmagent_proxy_image": VMAGENT_PROXY_IMAGE,
                "enable_tunnel_reuse": True,
                "vmsingle_image": VMSINGLE_IMAGE,
                "nodepool": nodepool,
            },
        )

        step_results.append({
            "node_count": tier,
            "targets_up": last_sample.get("targets_up", 0),
            "targets_total": last_sample.get("targets_total", 0),
            "measurements": step_measurements,
            "pass_criteria": step_pass_fail,
        })
        log.info("Step %d nodes: %s", tier, step_pass_fail.get("overall", "failure"))

    diagnostics = {}
    if not skip_diagnostics:
        try:
            diagnostics = collect_diagnostics(
                cp_kubeconfig, dp_kubeconfig, namespace, work_dir,
                include_fake_exporters=False)
        except Exception as e:
            log.warning("Diagnostics collection failed: %s", e)

    overall_result = "success" if all(
        s["pass_criteria"].get("overall") == "success" for s in step_results
    ) else "failure"

    result = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tiers": steps,
        "namespace": namespace,
        "mode": "real-targets-ramp",
        "config": {
            "warm_up_minutes": warm_up_minutes,
            "rate_limit": rate_limit,
            "max_block_size": max_block_size,
            "flush_interval": VMAGENT_FLUSH_INTERVAL,
            "queues": queues,
            "max_rows_per_block": max_rows_per_block,
            "konn_server_image": konn_server_image,
            "konn_agent_image": konn_agent_image,
            "vmagent_image": VMAGENT_IMAGE,
            "vmagent_proxy_image": VMAGENT_PROXY_IMAGE,
            "enable_tunnel_reuse": True,
            "vmsingle_image": VMSINGLE_IMAGE,
        },
        "steps": step_results,
        "resource_samples": all_samples,
        "diagnostics": diagnostics,
        "result": overall_result,
        "status": "completed",
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    label_suffix = f"-{run_label}" if run_label else ""
    results_file = results_dir / f"vmagent-loadtest-ramp-{run_id}{label_suffix}.json"
    results_file.write_text(json.dumps(result, indent=2))
    log.info("Ramp results: %s", results_file)

    if all_samples:
        import csv
        csv_file = results_dir / f"resource-usage-ramp-{run_id}{label_suffix}.csv"
        fieldnames = sorted({k for s in all_samples for k in s.keys()
                             if k not in ("vmagent", "konnectivity_server", "konnectivity_agent")})
        with open(csv_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_samples)
        log.info("Ramp resource usage CSV: %s", csv_file)

    return result


def cleanup_ramp(cp_kubeconfig: str, dp_kubeconfig: str, run_label: str = "",
                 mode: str = "real") -> None:
    """Clean up the single shared namespace used by a ramp run."""
    suffix = "ramp" if mode == "real" else "fake-ramp"
    namespace = f"loadtest-{run_label}-{suffix}" if run_label else f"loadtest-{suffix}"
    log.info("Cleaning up ramp namespace: %s", namespace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(_wait_ns_gone, cp_kubeconfig, namespace)
        pool.submit(_wait_ns_gone, dp_kubeconfig, namespace)
    log.info("Ramp cleanup complete.")


def run_fake_targets_ramp(cp_kubeconfig: str, dp_kubeconfig: str, tiers: list[int],
                          warm_up_minutes: int,
                          work_dir: Path, results_dir: Path, run_id: str,
                          resource_group: str = "", dp_cluster_name: str = "",
                          nodepool: str = DEFAULT_NODEPOOL,
                          run_label: str = "",
                          skip_diagnostics: bool = True,
                          rate_limit: int = VMAGENT_RATE_LIMIT,
                          max_block_size: int = 8388608,
                          queues: int = 8,
                          max_rows_per_block: int = 10000,
                          measure_drain: bool = False,
                          drain_observe_seconds: int = 120,
                          konn_server_image: str = KONN_SERVER_IMAGE,
                          konn_agent_image: str = KONN_AGENT_IMAGE) -> dict:
    """Ramp fake-exporter replicas through every tier in `tiers` (ascending)
    inside ONE continuous namespace/deployment, mirroring
    run_real_targets_ramp but scaling `scale_fake_exporters` (and the
    underlying DP nodepool via compute_fake_nodes_needed) instead of real
    DP nodes. At each step: scale exporters + DP nodepool, reconcile
    konnectivity-server/vmagent sizing for the new tier (idempotent
    applies), then dwell for `warm_up_minutes` sampling CPU/memory/
    restarts/OOMs/scrape health every 30s.
    """
    steps = sorted(set(tiers))
    namespace = f"loadtest-{run_label}-fake-ramp" if run_label else "loadtest-fake-ramp"

    log.info("")
    log.info("=" * 60)
    log.info("FAKE-TARGETS RAMP: %d -> %d replicas (%d steps: %s)",
             steps[0], steps[-1], len(steps), steps)
    log.info("=" * 60)

    def _reconcile_cp_stack(tier: int) -> tuple[int, int, dict]:
        proxied_targets = tier * len(FAKE_EXPORTER_ROLES) + tier + 50
        server_count = max(3, (proxied_targets + 1999) // 2000)
        return server_count, compute_shard_count(tier), compute_resources_for_tier(tier)

    # 1. Create namespaces (once for the whole ramp)
    ensure_namespace(cp_kubeconfig, namespace)
    ensure_namespace(dp_kubeconfig, namespace)

    # 2. Deploy konnectivity server sized for the first (smallest) step
    first_tier = steps[0]
    server_count, shard_count, tier_resources = _reconcile_cp_stack(first_tier)
    if resource_group and dp_cluster_name:
        scale_dp_nodepool(resource_group, dp_cluster_name, nodepool, compute_fake_nodes_needed(first_tier))
        wait_for_nodes_ready(dp_kubeconfig, expected=compute_fake_nodes_needed(first_tier), timeout_minutes=30)

    deploy_konnectivity_server(cp_kubeconfig, namespace, server_count=server_count,
                                resources=tier_resources["konn_server"], wait=False,
                                server_image=konn_server_image)
    server_ip = get_server_lb_ip(cp_kubeconfig, namespace)
    log.info("Konnectivity server LB IP: %s", server_ip)
    cert_dir = generate_certs(work_dir / "certs" / namespace, namespace, server_ip)
    create_cert_secret(cp_kubeconfig, namespace, cert_dir)
    create_cert_secret(dp_kubeconfig, namespace, cert_dir)
    rollout_restart(cp_kubeconfig, namespace, "deployment/konnectivity-server")

    deploy_fake_exporters(dp_kubeconfig, first_tier)
    deploy_konnectivity_agents(dp_kubeconfig, namespace, server_ip,
                                konnectivity_agent_replicas_for_node_count(compute_fake_nodes_needed(first_tier)),
                                agent_image=konn_agent_image)
    rollout_restart(dp_kubeconfig, namespace, "deployment/konnectivity-agent")

    setup_dp_access(dp_kubeconfig, cp_kubeconfig, namespace)
    dp_api_server = get_dp_api_server(dp_kubeconfig)

    deploy_vmsingle(cp_kubeconfig, namespace)
    deploy_vmagent(cp_kubeconfig, namespace, dp_api_server,
                   vmagent_resources=tier_resources["vmagent"],
                   proxy_resources=tier_resources["vmagent_proxy"],
                   replicas=shard_count,
                   rate_limit=rate_limit,
                   max_block_size=max_block_size,
                   queues=queues,
                   max_rows_per_block=max_rows_per_block)
    ramp_start_ts = time.time()

    all_samples: list[dict] = []
    step_results: list[dict] = []
    last_tier_resources = tier_resources

    for tier in steps:
        log.info("")
        log.info("-" * 60)
        log.info("RAMP STEP: scaling fake exporters to %d replicas", tier)
        log.info("-" * 60)
        step_start_ts = time.time()

        nodes_needed = compute_fake_nodes_needed(tier)
        if resource_group and dp_cluster_name:
            scale_dp_nodepool(resource_group, dp_cluster_name, nodepool, nodes_needed)
            wait_for_nodes_ready(dp_kubeconfig, expected=nodes_needed, timeout_minutes=30)

        scale_fake_exporters(dp_kubeconfig, tier)

        # Reconcile CP-side sizing for the new tier (idempotent applies)
        server_count, shard_count, tier_resources = _reconcile_cp_stack(tier)
        last_tier_resources = tier_resources
        deploy_konnectivity_server(cp_kubeconfig, namespace, server_count=server_count,
                                    resources=tier_resources["konn_server"], wait=True,
                                    server_image=konn_server_image)
        agent_replica_count = konnectivity_agent_replicas_for_node_count(nodes_needed)
        deploy_konnectivity_agents(dp_kubeconfig, namespace, server_ip, agent_replica_count,
                                    agent_image=konn_agent_image)
        deploy_vmagent(cp_kubeconfig, namespace, dp_api_server,
                       vmagent_resources=tier_resources["vmagent"],
                       proxy_resources=tier_resources["vmagent_proxy"],
                       replicas=shard_count,
                       rate_limit=rate_limit,
                       max_block_size=max_block_size,
                       queues=queues,
                       max_rows_per_block=max_rows_per_block)

        min_targets = int(tier * len(FAKE_EXPORTER_ROLES) * 0.95)

        log.info("Dwelling %dm at %d replicas (sampling every 30s)...", warm_up_minutes, tier)
        step_samples = dwell_and_sample(cp_kubeconfig, dp_kubeconfig, namespace,
                                        node_count=tier, duration_minutes=warm_up_minutes)
        all_samples.extend(step_samples)
        last_sample = step_samples[-1] if step_samples else {}

        step_measurements = collect_metrics(cp_kubeconfig, dp_kubeconfig, namespace, tier, work_dir)
        step_pass_fail = evaluate_pass_fail(step_measurements, expected_targets=min_targets)
        # Push this step's time series to ADX (no-op unless ADX_CLUSTER_URI/ADX_DATABASE set)
        adx_export_if_configured(cp_kubeconfig, namespace, run_id, tier,
                                  mode="fake-targets", start_ts=step_start_ts)
        step_measurements.update(adx_collect_resource_peaks(cp_kubeconfig, namespace, ramp_start_ts))

        adx_export_summary_if_configured(
            run_id=run_id,
            tier=tier,
            mode="fake-targets",
            result=step_pass_fail.get("overall", "failure"),
            measurements=step_measurements,
            pass_criteria=step_pass_fail,
            run_label=run_label or "",
            trial_label=f"ramp-step-{tier}",
            wall_time_seconds=time.time() - ramp_start_ts,
            dp_node_count=nodes_needed,
            konn_server_replicas=server_count,
            konn_agent_replicas=agent_replica_count,
            vmagent_replicas=shard_count,
            config={
                "warm_up_minutes": warm_up_minutes,
                "rate_limit": rate_limit,
                "max_block_size": max_block_size,
                "flush_interval": VMAGENT_FLUSH_INTERVAL,
                "queues": queues,
                "max_rows_per_block": max_rows_per_block,
                "konn_server_image": konn_server_image,
                "konn_agent_image": konn_agent_image,
                "vmagent_image": VMAGENT_IMAGE,
                "vmagent_proxy_image": VMAGENT_PROXY_IMAGE,
                "enable_tunnel_reuse": True,
                "vmsingle_image": VMSINGLE_IMAGE,
                "nodepool": nodepool,
            },
        )

        step_results.append({
            "node_count": tier,
            "targets_up": last_sample.get("targets_up", 0),
            "targets_total": last_sample.get("targets_total", 0),
            "measurements": step_measurements,
            "pass_criteria": step_pass_fail,
        })
        log.info("Step %d replicas: %s", tier, step_pass_fail.get("overall", "failure"))

    # Measure remote-write drain once, at the final (largest) tier reached --
    # pauses exporters, observes drain, then resumes back to the final tier.
    drain_stats = {}
    if measure_drain:
        paused_exporters = False
        try:
            scale_fake_exporters(dp_kubeconfig, 0)
            wait_for_fake_exporters_gone(dp_kubeconfig)
            settle_seconds = max(35, _flush_interval_seconds(VMAGENT_FLUSH_INTERVAL) + 15)
            log.info("Settling %ds after pausing exporters before drain observation...", settle_seconds)
            time.sleep(settle_seconds)
            paused_exporters = True
        except Exception as e:
            log.warning("Failed to pause fake exporters before drain observation: %s", e)
        log.info("Observing remote-write drain for %ds...", drain_observe_seconds)
        try:
            drain_stats = observe_remotewrite_drain(
                cp_kubeconfig, namespace, work_dir, duration_seconds=drain_observe_seconds)
            drain_stats["remotewrite_drain_exporters_paused"] = paused_exporters
        finally:
            if paused_exporters:
                try:
                    scale_fake_exporters(dp_kubeconfig, steps[-1])
                except Exception as e:
                    log.warning("Failed to resume fake exporters after drain observation: %s", e)

    diagnostics = {}
    if not skip_diagnostics:
        try:
            diagnostics = collect_diagnostics(
                cp_kubeconfig, dp_kubeconfig, namespace, work_dir,
                include_fake_exporters=True)
        except Exception as e:
            log.warning("Diagnostics collection failed: %s", e)

    overall_result = "success" if all(
        s["pass_criteria"].get("overall") == "success" for s in step_results
    ) else "failure"

    result = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tiers": steps,
        "namespace": namespace,
        "mode": "fake-targets-ramp",
        "config": {
            "warm_up_minutes": warm_up_minutes,
            "rate_limit": rate_limit,
            "max_block_size": max_block_size,
            "flush_interval": VMAGENT_FLUSH_INTERVAL,
            "queues": queues,
            "max_rows_per_block": max_rows_per_block,
            "konn_server_image": konn_server_image,
            "konn_agent_image": konn_agent_image,
            "vmagent_image": VMAGENT_IMAGE,
            "vmagent_proxy_image": VMAGENT_PROXY_IMAGE,
            "enable_tunnel_reuse": True,
            "vmsingle_image": VMSINGLE_IMAGE,
        },
        "steps": step_results,
        "resource_samples": all_samples,
        "drain": drain_stats,
        "diagnostics": diagnostics,
        "result": overall_result,
        "status": "completed",
    }

    results_dir.mkdir(parents=True, exist_ok=True)
    label_suffix = f"-{run_label}" if run_label else ""
    results_file = results_dir / f"vmagent-loadtest-fake-ramp-{run_id}{label_suffix}.json"
    results_file.write_text(json.dumps(result, indent=2))
    log.info("Ramp results: %s", results_file)

    if all_samples:
        import csv
        csv_file = results_dir / f"resource-usage-fake-ramp-{run_id}{label_suffix}.csv"
        fieldnames = sorted({k for s in all_samples for k in s.keys()
                             if k not in ("vmagent", "konnectivity_server", "konnectivity_agent")})
        with open(csv_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_samples)
        log.info("Ramp resource usage CSV: %s", csv_file)

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
