#!/usr/bin/env python3
"""
main.py — Orchestrate fake control plane load test

Architecture:
  Cluster 1 (Control Plane): konnectivity-server + VMAgent per test namespace
  Cluster 2 (Dataplane):     fake exporters (4 roles × N replicas) + konnectivity-agent per test

Usage:
  python3 main.py --cp-kubeconfig <path> --dp-kubeconfig <path> [OPTIONS]

Options:
  --cp-kubeconfig PATH    Control plane cluster kubeconfig
  --dp-kubeconfig PATH    Dataplane cluster kubeconfig
  --tiers 150,500,1000    Comma-separated replicas-per-role per tier (total targets = tier × 4)
  --warm-up-minutes N     Warm-up time per tier (default: 5)
  --cleanup               Delete all loadtest namespaces and exit
"""

import argparse
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Add package parent to path so the modules package is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vmagent_loadtest.cluster import az_login, create_clusters, delete_resource_group
from vmagent_loadtest.compare import compare_real_vs_fake, compare_cross_tier
from vmagent_loadtest.config import (
    DEFAULT_CP_CLUSTER_NAME, DEFAULT_CP_NODEPOOL, DEFAULT_NODEPOOL,
    KONN_AGENT_IMAGE, KONN_SERVER_IMAGE, VMAGENT_RATE_LIMIT, log,
)
from vmagent_loadtest.runner import (
    cleanup, cleanup_ramp, cleanup_tier, compute_fake_nodes_needed,
    run_fake_targets_ramp, run_real_targets_ramp, run_single_tier,
)
from vmagent_loadtest.scaling import (
    scale_dp_nodepool, scale_down_for_teardown, wait_for_nodes_ready, delete_fanout_nodepools,
)
from vmagent_loadtest import utils as _utils


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake Control Plane Load Test")

    # Cluster lifecycle flags (mutually exclusive with test run)
    cluster_group = parser.add_argument_group("Cluster lifecycle")
    cluster_group.add_argument("--create-clusters", action="store_true",
                               help="Create CP + DP AKS clusters and exit")
    cluster_group.add_argument("--delete-clusters", action="store_true",
                               help="Delete the resource group and exit")
    cluster_group.add_argument("--msi-client-id", default="",
                               help="MSI client ID for Azure login")
    cluster_group.add_argument("--subscription-id", default="",
                               help="Azure subscription ID")
    cluster_group.add_argument("--cp-cluster-name", default=DEFAULT_CP_CLUSTER_NAME,
                               help=f"Control plane AKS cluster name (default: {DEFAULT_CP_CLUSTER_NAME})")
    cluster_group.add_argument("--cp-node-count", type=int, default=5,
                               help="CP cluster node count (default: 5)")
    cluster_group.add_argument("--dp-node-count", type=int, default=10,
                               help="DP cluster node count (default: 10)")
    cluster_group.add_argument("--location", default="eastus",
                               help="Azure region (default: eastus)")
    cluster_group.add_argument("--vm-size", default="Standard_D2_v3",
                               help="VM size (default: Standard_D2_v3)")
    cluster_group.add_argument("--max-pods", type=int, default=250,
                               help="Max pods per node (default: 250)")
    cluster_group.add_argument("--kubeconfig-dir", default="",
                               help="Directory to write kubeconfigs to")

    # Test run flags
    parser.add_argument("--cp-kubeconfig", default="", help="Control plane cluster kubeconfig")
    parser.add_argument("--dp-kubeconfig", default="", help="Dataplane cluster kubeconfig")
    parser.add_argument("--tiers", default="150,500,1000",
                        help="Comma-separated replicas-per-role per tier (total targets = tier × 4)")
    parser.add_argument("--warm-up-minutes", type=int, default=5,
                        help="Warm-up time per tier (default: 5)")
    parser.add_argument("--final-tier-dwell-minutes", type=int, default=5,
                        help="Ramp modes only: after the FINAL (highest) tier's nodes are "
                             "Ready, dwell this long before collecting the metrics that "
                             "determine the ramp's overall pass/fail (default: 5). "
                             "Intermediate tiers don't gate on scrape coverage, but the "
                             "final tier's result does, so it needs real time for SD "
                             "discovery + scrape cycles to catch up. Set to 0 to disable.")
    parser.add_argument("--cleanup", action="store_true",
                        help="Delete all loadtest namespaces and exit")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--real-targets", action="store_true",
                        help="Scrape real kubelet/cadvisor/kube-proxy instead of fake exporters")
    parser.add_argument("--resource-group", default="",
                        help="Azure resource group for DP cluster (enables node scaling)")
    parser.add_argument("--dp-cluster-name", default="",
                        help="AKS cluster name for DP cluster (enables node scaling)")
    parser.add_argument("--nodepool-name", default=DEFAULT_NODEPOOL,
                        help=f"DP cluster nodepool name (default: {DEFAULT_NODEPOOL})")
    parser.add_argument("--cp-nodepool-name", default=DEFAULT_CP_NODEPOOL,
                        help=f"CP cluster nodepool name (default: {DEFAULT_CP_NODEPOOL}); "
                             f"scaled per-tier to the CPU konn-server/vmagent need "
                             f"(see config.compute_cp_nodes_needed) instead of relying "
                             f"on the fixed terraform node count")
    parser.add_argument("--max-retries", type=int, default=2,
                        help="Max retries per tier on failure (default: 2)")
    parser.add_argument("--rate-limit", type=int, default=VMAGENT_RATE_LIMIT,
                        help=f"-remoteWrite.rateLimit bytes/sec passed to vmagent "
                             f"(default: {VMAGENT_RATE_LIMIT} = 2 MiB/s, matches prod; "
                             f"prod's own 2k-node test found even this insufficient — "
                             f"raise further to validate)")
    parser.add_argument("--max-block-size", type=int, default=8388608,
                        help="-remoteWrite.maxBlockSize bytes passed to vmagent "
                             "(default: 8388608 = 8 MiB, VictoriaMetrics stock default; "
                             "prod is still pinned at the old 524288 = .5 MiB — this is "
                             "a pending/unvalidated recommendation this load test exists "
                             "to confirm)")
    parser.add_argument("--konn-server-image", default=KONN_SERVER_IMAGE,
                        help=f"konnectivity-server image to deploy "
                             f"(default: {KONN_SERVER_IMAGE}). Use this to load-test "
                             f"a custom/fix image before it ships to prod.")
    parser.add_argument("--konn-agent-image", default=KONN_AGENT_IMAGE,
                        help=f"konnectivity-agent image to deploy (default: {KONN_AGENT_IMAGE})")
    parser.add_argument("--measure-drain", action="store_true",
                        help="After metrics collection, poll "
                             "vmagent_remotewrite_pending_data_bytes over a fixed "
                             "window to directly measure backlog drain rate under "
                             "continued normal operation (preStop-hook proxy test)")
    parser.add_argument("--drain-observe-seconds", type=int, default=120,
                        help="Observation window for --measure-drain (default: 120)")
    parser.add_argument("--collect-diagnostics", action="store_true",
                        help="Collect pprof + per-pod log/diagnostics. Default "
                             "is to SKIP them (much faster). Opt in only when "
                             "debugging a failure.")
    parser.add_argument("--run-label", default="",
                        help="Label prefix for namespaces (avoids collisions in parallel runs)")
    parser.add_argument("--parallel", action="store_true",
                        help="Run all fake-mode tiers concurrently in separate namespaces "
                             "(no-op for --real-targets; DP nodepool is pre-sized to the sum "
                             "of all tiers' node demand)")
    parser.add_argument("--max-concurrency", type=int, default=0,
                        help="Cap on concurrent tiers when --parallel is set (default: all tiers at once)")
    parser.add_argument("--compare", action="store_true",
                        help="Run both real and fake modes for the first tier, then produce a real-vs-fake fidelity report")
    parser.add_argument("--compare-results", nargs=2, metavar=("REAL_JSON", "FAKE_JSON"),
                        help="Real-vs-fake: compare two existing result JSON files without running tests")
    parser.add_argument("--compare-tiers", nargs="+", metavar="JSON",
                        help="Cross-tier: compare multiple tier result JSON files to see how metrics scale with load")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Azure SDK HTTP pipeline loggers (used internally by Kusto's
    # QueuedIngestClient, which is backed by Azure Storage Queue/Blob)
    # dump full request/response headers at INFO level otherwise --
    # noisy and not useful for this pipeline's logs.
    for noisy_logger in (
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.storage.queue", "azure.storage.blob", "azure.storage.common",
        "azure.identity", "azure.kusto.data", "urllib3.connectionpool",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # --- Compare existing results: real vs fake ---
    if args.compare_results:
        real_path, fake_path = args.compare_results
        real_data = json.loads(Path(real_path).read_text())
        fake_data = json.loads(Path(fake_path).read_text())
        report = compare_real_vs_fake(real_data, fake_data)
        report_file = Path(f"comparison-real-vs-fake-tier{real_data.get('tier', 'unknown')}.md")
        report_file.write_text(report)
        print(report)
        log.info("Report saved to %s", report_file)
        return

    # --- Compare existing results: cross-tier scaling ---
    if args.compare_tiers:
        results = []
        for p in args.compare_tiers:
            results.append(json.loads(Path(p).read_text()))
        report = compare_cross_tier(results)
        mode = results[0].get("mode", "unknown")
        report_file = Path(f"comparison-cross-tier-{mode}.md")
        report_file.write_text(report)
        print(report)
        log.info("Report saved to %s", report_file)
        return

    # --- Cluster lifecycle modes ---
    if args.create_clusters or args.delete_clusters:
        if not args.subscription_id:
            parser.error("--subscription-id is required for cluster operations")
        az_login(args.msi_client_id, args.subscription_id)

        if args.delete_clusters:
            if not args.resource_group:
                parser.error("--resource-group is required for --delete-clusters")
            delete_resource_group(args.resource_group)
            return

        if args.create_clusters:
            if not all([args.resource_group, args.cp_cluster_name, args.dp_cluster_name, args.kubeconfig_dir]):
                parser.error("--resource-group, --cp-cluster-name, --dp-cluster-name, and --kubeconfig-dir are required for --create-clusters")
            cp_kc, dp_kc = create_clusters(
                resource_group=args.resource_group,
                cp_cluster=args.cp_cluster_name,
                dp_cluster=args.dp_cluster_name,
                location=args.location,
                cp_node_count=args.cp_node_count,
                dp_node_count=args.dp_node_count,
                vm_size=args.vm_size,
                kubeconfig_dir=args.kubeconfig_dir,
                max_pods=args.max_pods,
            )
            # Print paths for pipeline to capture
            print(f"CP_KUBECONFIG={cp_kc}")
            print(f"DP_KUBECONFIG={dp_kc}")
            return

    # --- Compare mode: run real + fake for tier=10, then compare ---
    if args.compare:
        if not args.cp_kubeconfig or not args.dp_kubeconfig:
            parser.error("--cp-kubeconfig and --dp-kubeconfig are required for --compare")
        if not args.resource_group or not args.dp_cluster_name:
            parser.error("--resource-group and --dp-cluster-name are required for --compare (node scaling)")

        tier = int(args.tiers.split(",")[0]) if args.tiers else 10
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        work_dir = Path(tempfile.mkdtemp(prefix="vmagent-loadtest."))
        results_dir = work_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        log.info("=" * 60)
        log.info("COMPARISON MODE: real vs fake @ tier=%d", tier)
        log.info("  Work dir: %s", work_dir)
        log.info("=" * 60)

        # 1. Run real-targets test
        log.info("")
        log.info(">>> Phase 1: REAL TARGETS (tier=%d)", tier)
        real_result = run_single_tier(
            cp_kubeconfig=args.cp_kubeconfig,
            dp_kubeconfig=args.dp_kubeconfig,
            tier=tier,
            warm_up_minutes=args.warm_up_minutes,
            work_dir=work_dir,
            results_dir=results_dir,
            run_id=run_id,
            real_targets=True,
            resource_group=args.resource_group,
            dp_cluster_name=args.dp_cluster_name,
            nodepool=args.nodepool_name,
            run_label="real",
            rate_limit=args.rate_limit,
            max_block_size=args.max_block_size,
            measure_drain=args.measure_drain,
            drain_observe_seconds=args.drain_observe_seconds,
            konn_server_image=args.konn_server_image,
            konn_agent_image=args.konn_agent_image,
        )
        cleanup_tier(args.cp_kubeconfig, args.dp_kubeconfig, tier, run_label="real")

        # 2. Run fake-exporter test
        log.info("")
        log.info(">>> Phase 2: FAKE EXPORTER (tier=%d)", tier)
        fake_result = run_single_tier(
            cp_kubeconfig=args.cp_kubeconfig,
            dp_kubeconfig=args.dp_kubeconfig,
            tier=tier,
            warm_up_minutes=args.warm_up_minutes,
            work_dir=work_dir,
            results_dir=results_dir,
            run_id=run_id,
            real_targets=False,
            resource_group=args.resource_group,
            dp_cluster_name=args.dp_cluster_name,
            nodepool=args.nodepool_name,
            run_label="fake",
            rate_limit=args.rate_limit,
            max_block_size=args.max_block_size,
            measure_drain=args.measure_drain,
            drain_observe_seconds=args.drain_observe_seconds,
            konn_server_image=args.konn_server_image,
            konn_agent_image=args.konn_agent_image,
        )
        cleanup_tier(args.cp_kubeconfig, args.dp_kubeconfig, tier, run_label="fake")

        # 3. Generate comparison report
        report = compare_real_vs_fake(real_result, fake_result)
        report_file = results_dir / f"comparison-real-vs-fake-tier{tier}.md"
        report_file.write_text(report)
        print(report)
        log.info("Comparison report: %s", report_file)
        log.info("All results: %s", results_dir)
        return

    # --- Test run mode ---
    if not args.cp_kubeconfig or not args.dp_kubeconfig:
        parser.error("--cp-kubeconfig and --dp-kubeconfig are required for test run")

    tiers = [int(t.strip()) for t in args.tiers.split(",")]
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    log.info("=" * 60)
    log.info("Vmagent Load Test")
    log.info("  Tiers:    %s", tiers)
    log.info("  Warm-up:  %dm per tier", args.warm_up_minutes)
    log.info("  CP:       %s", args.cp_kubeconfig)
    log.info("  DP:       %s", args.dp_kubeconfig)
    if args.real_targets:
        log.info("  Mode:     REAL TARGETS (kubelet/cadvisor/kube-proxy)")
    if args.resource_group and args.dp_cluster_name:
        log.info("  Scaling:  %s/%s (nodepool: %s)",
                 args.resource_group, args.dp_cluster_name, args.nodepool_name)
        log.info("  Tiers are DP node counts: %s", tiers)
    log.info("=" * 60)

    work_dir = Path(tempfile.mkdtemp(prefix="vmagent-loadtest."))
    results_dir = work_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    log.info("Work dir: %s", work_dir)

    if args.cleanup:
        cleanup(args.cp_kubeconfig, args.dp_kubeconfig)
        if args.resource_group and args.dp_cluster_name:
            delete_fanout_nodepools(args.resource_group, args.dp_cluster_name, args.nodepool_name)
        return

    parallel_mode = (args.parallel and not args.real_targets and len(tiers) > 1)
    if args.parallel and args.real_targets:
        log.warning("--parallel ignored: real-targets mode reshapes the cluster per tier, must run sequentially")
    if args.parallel and len(tiers) <= 1:
        log.info("--parallel no-op: only one tier given")

    all_results = []
    failed_tiers = []

    if parallel_mode:
        # Pre-size DP nodepool to sum of all tiers' node demand, then fan out.
        per_tier_nodes = {t: compute_fake_nodes_needed(t) for t in tiers}
        total_nodes = sum(per_tier_nodes.values())
        log.info("=" * 60)
        log.info("PARALLEL MODE — %d fake-mode tiers in flight", len(tiers))
        for t, n in per_tier_nodes.items():
            log.info("  tier %-5d → %d DP nodes", t, n)
        log.info("  total DP nodes needed: %d", total_nodes)
        if args.max_concurrency:
            log.info("  max concurrency: %d", args.max_concurrency)
        log.info("=" * 60)

        if args.resource_group and args.dp_cluster_name:
            log.info("Pre-scaling DP nodepool %s to %d nodes (one-shot)",
                     args.nodepool_name, total_nodes)
            scale_dp_nodepool(args.resource_group, args.dp_cluster_name,
                              args.nodepool_name, total_nodes)
            wait_for_nodes_ready(args.dp_kubeconfig, expected=total_nodes,
                                 timeout_minutes=45)

        # Make every PortForward in worker threads bind a free ephemeral port
        # instead of the hardcoded 18096/18428/18429 → no cross-tier collisions.
        _utils._AUTO_PORT_FORWARD = True

        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = args.max_concurrency or len(tiers)
        with ThreadPoolExecutor(max_workers=max_workers,
                                thread_name_prefix="tier") as pool:
            futures = {}
            for tier in tiers:
                fut = pool.submit(
                    run_single_tier,
                    cp_kubeconfig=args.cp_kubeconfig,
                    dp_kubeconfig=args.dp_kubeconfig,
                    tier=tier,
                    warm_up_minutes=args.warm_up_minutes,
                    work_dir=work_dir,
                    results_dir=results_dir,
                    run_id=run_id,
                    real_targets=False,
                    # Empty rg/cluster → run_single_tier skips its own scaling
                    resource_group="",
                    dp_cluster_name="",
                    nodepool=args.nodepool_name,
                    run_label=args.run_label,
                    rate_limit=args.rate_limit,
                    max_block_size=args.max_block_size,
                    measure_drain=args.measure_drain,
                    drain_observe_seconds=args.drain_observe_seconds,
                    konn_server_image=args.konn_server_image,
                    konn_agent_image=args.konn_agent_image,
                )
                futures[fut] = tier

            for fut in as_completed(futures):
                tier = futures[fut]
                try:
                    result = fut.result()
                    all_results.append(result)
                    log.info("Tier %d completed", tier)
                except Exception as e:
                    log.error("Tier %d FAILED in parallel run: %s", tier, e)
                    failed_tiers.append(tier)
                    all_results.append({
                        "run_id": run_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "tier": tier,
                        "status": "failed",
                        "error": str(e),
                    })
                finally:
                    try:
                        cleanup_tier(args.cp_kubeconfig, args.dp_kubeconfig, tier,
                                     run_label=args.run_label)
                    except Exception as ce:
                        log.warning("cleanup_tier(%d) failed: %s", tier, ce)

        _utils._AUTO_PORT_FORWARD = False
    elif args.real_targets:
        # Real targets ramp through every tier as DP node counts inside ONE
        # continuous deployment (see run_real_targets_ramp) instead of
        # tearing down and redeploying per tier. On failure, retry starting
        # AT the failed tier (resume=True) instead of re-ramping from tier
        # 500 -- avoids redoing already-passed tiers (wasted time + nodes)
        # and double-counting their data in ADX. Only falls back to a full
        # cleanup+restart-from-scratch if the failure happened outside the
        # per-tier loop (no .failed_tier to resume from).
        remaining_tiers = list(tiers)
        last_exc = None
        for attempt in range(1, args.max_retries + 2):
            resume = False
            try:
                if attempt > 1:
                    failed_tier = getattr(last_exc, "failed_tier", None)
                    if failed_tier is not None and failed_tier in remaining_tiers:
                        completed = [t for t in tiers if t < failed_tier]
                        remaining_tiers = remaining_tiers[remaining_tiers.index(failed_tier):]
                        resume = True
                        log.info("RETRY %d/%d for ramp — resuming at tier %d (tiers %s "
                                "already completed, not re-run)...",
                                attempt - 1, args.max_retries, failed_tier, completed)
                    else:
                        log.info("RETRY %d/%d for ramp — cleaning up previous attempt "
                                "(no tier checkpoint to resume from)...",
                                attempt - 1, args.max_retries)
                        cleanup_ramp(args.cp_kubeconfig, args.dp_kubeconfig,
                                    run_label=args.run_label, mode="real")
                        remaining_tiers = list(tiers)
                result = run_real_targets_ramp(
                    cp_kubeconfig=args.cp_kubeconfig,
                    dp_kubeconfig=args.dp_kubeconfig,
                    tiers=remaining_tiers,
                    warm_up_minutes=args.warm_up_minutes,
                    work_dir=work_dir,
                    results_dir=results_dir,
                    run_id=run_id,
                    resource_group=args.resource_group,
                    dp_cluster_name=args.dp_cluster_name,
                    nodepool=args.nodepool_name,
                    cp_cluster_name=args.cp_cluster_name,
                    cp_nodepool=args.cp_nodepool_name,
                    run_label=args.run_label,
                    skip_diagnostics=not args.collect_diagnostics,
                    rate_limit=args.rate_limit,
                    max_block_size=args.max_block_size,
                    konn_server_image=args.konn_server_image,
                    konn_agent_image=args.konn_agent_image,
                    resume=resume,
                    final_tier_dwell_minutes=args.final_tier_dwell_minutes,
                )
                all_results.append(result)
                break
            except Exception as e:
                last_exc = e
                log.error("Ramp attempt %d FAILED (tier=%s): %s",
                         attempt, getattr(e, "failed_tier", "unknown"), e)
                if attempt == args.max_retries + 1:
                    log.error("Ramp FAILED after %d attempts — saving error", attempt)
                    result = {
                        "run_id": run_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "tiers": tiers,
                        "status": "failed",
                        "error": str(e),
                        "attempts": attempt,
                    }
                    err_file = results_dir / f"vmagent-loadtest-ramp-{run_id}.json"
                    err_file.write_text(json.dumps(result, indent=2))
                    all_results.append(result)
                    failed_tiers.extend(tiers)
        cleanup_ramp(args.cp_kubeconfig, args.dp_kubeconfig, run_label=args.run_label, mode="real")
        scale_down_for_teardown(args.resource_group, args.dp_cluster_name, args.nodepool_name,
                               cp_cluster_name=args.cp_cluster_name, cp_nodepool=args.cp_nodepool_name)
    else:
        # Fake targets ramp through every tier as exporter replica counts
        # inside ONE continuous deployment (see run_fake_targets_ramp)
        # instead of tearing down and redeploying per tier. On failure,
        # retry starting AT the failed tier (see real-targets branch above
        # for the rationale).
        remaining_tiers = list(tiers)
        last_exc = None
        for attempt in range(1, args.max_retries + 2):
            resume = False
            try:
                if attempt > 1:
                    failed_tier = getattr(last_exc, "failed_tier", None)
                    if failed_tier is not None and failed_tier in remaining_tiers:
                        completed = [t for t in tiers if t < failed_tier]
                        remaining_tiers = remaining_tiers[remaining_tiers.index(failed_tier):]
                        resume = True
                        log.info("RETRY %d/%d for ramp — resuming at tier %d (tiers %s "
                                "already completed, not re-run)...",
                                attempt - 1, args.max_retries, failed_tier, completed)
                    else:
                        log.info("RETRY %d/%d for ramp — cleaning up previous attempt "
                                "(no tier checkpoint to resume from)...",
                                attempt - 1, args.max_retries)
                        cleanup_ramp(args.cp_kubeconfig, args.dp_kubeconfig,
                                    run_label=args.run_label, mode="fake")
                        remaining_tiers = list(tiers)
                result = run_fake_targets_ramp(
                    cp_kubeconfig=args.cp_kubeconfig,
                    dp_kubeconfig=args.dp_kubeconfig,
                    tiers=remaining_tiers,
                    warm_up_minutes=args.warm_up_minutes,
                    work_dir=work_dir,
                    results_dir=results_dir,
                    run_id=run_id,
                    resource_group=args.resource_group,
                    dp_cluster_name=args.dp_cluster_name,
                    nodepool=args.nodepool_name,
                    cp_cluster_name=args.cp_cluster_name,
                    cp_nodepool=args.cp_nodepool_name,
                    run_label=args.run_label,
                    skip_diagnostics=not args.collect_diagnostics,
                    rate_limit=args.rate_limit,
                    max_block_size=args.max_block_size,
                    measure_drain=args.measure_drain,
                    drain_observe_seconds=args.drain_observe_seconds,
                    konn_server_image=args.konn_server_image,
                    konn_agent_image=args.konn_agent_image,
                    resume=resume,
                    final_tier_dwell_minutes=args.final_tier_dwell_minutes,
                )
                all_results.append(result)
                break
            except Exception as e:
                last_exc = e
                log.error("Ramp attempt %d FAILED (tier=%s): %s",
                         attempt, getattr(e, "failed_tier", "unknown"), e)
                if attempt == args.max_retries + 1:
                    log.error("Ramp FAILED after %d attempts — saving error", attempt)
                    result = {
                        "run_id": run_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "tiers": tiers,
                        "status": "failed",
                        "error": str(e),
                        "attempts": attempt,
                    }
                    err_file = results_dir / f"vmagent-loadtest-fake-ramp-{run_id}.json"
                    err_file.write_text(json.dumps(result, indent=2))
                    all_results.append(result)
                    failed_tiers.extend(tiers)
        cleanup_ramp(args.cp_kubeconfig, args.dp_kubeconfig, run_label=args.run_label, mode="fake")
        scale_down_for_teardown(args.resource_group, args.dp_cluster_name, args.nodepool_name,
                               cp_cluster_name=args.cp_cluster_name, cp_nodepool=args.cp_nodepool_name)

    log.info("")
    log.info("=" * 60)
    if failed_tiers:
        log.info("TIERS COMPLETE — %d passed, %d failed: %s",
                 len(tiers) - len(failed_tiers), len(failed_tiers), failed_tiers)
    else:
        log.info("ALL TIERS COMPLETE")
    log.info("  Results: %s", results_dir)
    log.info("=" * 60)

    for r in all_results:
        if r.get("status") == "failed":
            tiers_desc = r.get("tiers", r.get("tier"))
            log.info("  tiers=%s FAILED: %s", tiers_desc, r.get("error", "unknown"))
            continue
        if r.get("mode") in ("real-targets-ramp", "fake-targets-ramp"):
            for step in r.get("steps", []):
                log.info(
                    "  count=%-5d scrape=%d/%d result=%s",
                    step["node_count"], step["targets_up"], step["targets_total"],
                    step["pass_criteria"].get("overall", "failure"),
                )
            continue
        m = r["measurements"]
        log.info(
            "  tier=%-5d scrape=%d/%d (%.1f%%) dial_mean=%.4fs oom=%d result=%s",
            r["tier"],
            m["scrape_targets_up"], m["scrape_targets_total"],
            m["scrape_success_rate"] * 100,
            m.get("konn_server_dial_mean_seconds", 0),
            m["oom_events"],
            r.get("result", "failure"),
        )

    for f in sorted(results_dir.glob("*.json")):
        log.info("  %s", f)

    # Auto-generate cross-tier scaling report only for the parallel fan-out
    # case, where tiers are still genuinely independent runs (sequential
    # real/fake runs are now a single continuous ramp with its own
    # step-by-step data captured inside the ramp result itself).
    completed = [r for r in all_results if r.get("status") == "completed"]
    if len(completed) >= 2 and parallel_mode:
        report = compare_cross_tier(completed)
        report_file = results_dir / "comparison-cross-tier-fake-targets.md"
        report_file.write_text(report)
        log.info("Cross-tier scaling report: %s", report_file)


if __name__ == "__main__":
    main()
