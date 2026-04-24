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
from vmagent_loadtest.compare import compare
from vmagent_loadtest.config import DEFAULT_NODEPOOL, log
from vmagent_loadtest.runner import cleanup, cleanup_tier, run_single_tier


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
    cluster_group.add_argument("--cp-cluster-name", default="",
                               help="Control plane AKS cluster name")
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
    parser.add_argument("--max-retries", type=int, default=2,
                        help="Max retries per tier on failure (default: 2)")
    parser.add_argument("--run-label", default="",
                        help="Label prefix for namespaces (avoids collisions in parallel runs)")
    parser.add_argument("--compare", action="store_true",
                        help="Run both real and fake modes for tier=10, then produce comparison report")
    parser.add_argument("--compare-results", nargs=2, metavar=("REAL_JSON", "FAKE_JSON"),
                        help="Compare two existing result JSON files (real, fake) without running tests")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Compare existing results mode ---
    if args.compare_results:
        real_path, fake_path = args.compare_results
        real_data = json.loads(Path(real_path).read_text())
        fake_data = json.loads(Path(fake_path).read_text())
        report = compare(real_data, fake_data)
        report_file = Path(f"comparison-report-{real_data.get('tier', 'unknown')}.md")
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
        work_dir = Path(tempfile.mkdtemp(prefix="fake-cp-loadtest."))
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
        )
        cleanup_tier(args.cp_kubeconfig, args.dp_kubeconfig, tier, run_label="fake")

        # 3. Generate comparison report
        report = compare(real_result, fake_result)
        report_file = results_dir / f"comparison-report-tier{tier}.md"
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

    work_dir = Path(tempfile.mkdtemp(prefix="fake-cp-loadtest."))
    results_dir = work_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    log.info("Work dir: %s", work_dir)

    if args.cleanup:
        cleanup(args.cp_kubeconfig, args.dp_kubeconfig)
        return

    all_results = []
    failed_tiers = []
    for tier in tiers:
        result = None
        for attempt in range(1, args.max_retries + 2):  # +2 because first attempt + retries
            try:
                if attempt > 1:
                    log.info("RETRY %d/%d for tier %d — cleaning up previous attempt...",
                             attempt - 1, args.max_retries, tier)
                    cleanup_tier(args.cp_kubeconfig, args.dp_kubeconfig, tier,
                                 run_label=args.run_label)
                result = run_single_tier(
                    cp_kubeconfig=args.cp_kubeconfig,
                    dp_kubeconfig=args.dp_kubeconfig,
                    tier=tier,
                    warm_up_minutes=args.warm_up_minutes,
                    work_dir=work_dir,
                    results_dir=results_dir,
                    run_id=run_id,
                    real_targets=args.real_targets,
                    resource_group=args.resource_group,
                    dp_cluster_name=args.dp_cluster_name,
                    nodepool=args.nodepool_name,
                    run_label=args.run_label,
                )
                break
            except Exception as e:
                log.error("Tier %d attempt %d FAILED: %s", tier, attempt, e)
                if attempt == args.max_retries + 1:
                    log.error("Tier %d FAILED after %d attempts — saving error and continuing",
                              tier, attempt)
                    result = {
                        "run_id": run_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "tier": tier,
                        "status": "failed",
                        "error": str(e),
                        "attempts": attempt,
                    }
                    err_file = results_dir / f"vmagent-loadtest-{run_id}-{tier}.json"
                    err_file.write_text(json.dumps(result, indent=2))
                    failed_tiers.append(tier)

        if result:
            all_results.append(result)

        # Clean up this tier's namespaces before moving to the next one
        # to free CP/DP resources (konnectivity, vmagent, vmsingle).
        if len(tiers) > 1:
            cleanup_tier(args.cp_kubeconfig, args.dp_kubeconfig, tier,
                         run_label=args.run_label)

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
            log.info("  tier=%-5d FAILED: %s", r["tier"], r.get("error", "unknown"))
            continue
        m = r["measurements"]
        log.info(
            "  tier=%-5d scrape=%d/%d (%.1f%%) dial_mean=%.4fs oom=%d pass=%s",
            r["tier"],
            m["scrape_targets_up"], m["scrape_targets_total"],
            m["scrape_success_rate"] * 100,
            m.get("konn_server_dial_mean_seconds", 0),
            m["oom_events"],
            "PASS" if r["pass"] else "FAIL",
        )

    for f in sorted(results_dir.glob("*.json")):
        log.info("  %s", f)


if __name__ == "__main__":
    main()
