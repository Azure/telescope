"""Metrics collection, target polling, and pass/fail evaluation."""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from .config import FAKE_EXPORTER_NS, FAKE_EXPORTER_ROLES, log
from .utils import PortForward, kubectl, retry_request


def extract_prom_value(metrics_text: str, pattern: str) -> float:
    for line in metrics_text.split("\n"):
        if re.search(pattern, line):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return float(parts[-1])
                except ValueError:
                    pass
    return 0.0


def extract_prom_sum(metrics_text: str, pattern: str) -> float:
    total = 0.0
    for line in metrics_text.split("\n"):
        if re.search(pattern, line):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    total += float(parts[-1])
                except ValueError:
                    pass
    return total


def extract_histogram_percentiles(metrics_text: str, metric_name: str,
                                   percentiles: tuple = (0.5, 0.9, 0.99)) -> dict:
    """Extract percentiles from a Prometheus histogram using bucket boundaries.

    Returns dict with p50, p90, p99 (or whatever percentiles are requested),
    plus sum, count, and mean.
    """
    result = {"sum": 0.0, "count": 0.0, "mean": 0.0}
    for p in percentiles:
        result[f"p{int(p*100)}"] = None

    buckets = []  # list of (le, count)
    for line in metrics_text.split("\n"):
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        if line.startswith(f"{metric_name}_bucket"):
            le_match = re.search(r'le="([^"]+)"', line)
            val_parts = line.rsplit(None, 1)
            if le_match and len(val_parts) >= 2:
                try:
                    le = float(le_match.group(1)) if le_match.group(1) != "+Inf" else float("inf")
                    count = float(val_parts[-1])
                    buckets.append((le, count))
                except ValueError:
                    pass
        elif line.startswith(f"{metric_name}_sum"):
            parts = line.rsplit(None, 1)
            if len(parts) >= 2:
                try:
                    result["sum"] = float(parts[-1])
                except ValueError:
                    pass
        elif line.startswith(f"{metric_name}_count"):
            parts = line.rsplit(None, 1)
            if len(parts) >= 2:
                try:
                    result["count"] = float(parts[-1])
                except ValueError:
                    pass

    if result["count"] > 0:
        result["mean"] = round(result["sum"] / result["count"], 6)

    if buckets:
        buckets.sort(key=lambda x: x[0])
        total = buckets[-1][1] if buckets else 0
        for p in percentiles:
            threshold = total * p
            for le, count in buckets:
                if count >= threshold and le != float("inf"):
                    result[f"p{int(p*100)}"] = le
                    break

    return result


def count_pods(kubeconfig: str, namespace: str, label: str) -> int:
    result = kubectl(kubeconfig, "-n", namespace, "get", "pods",
                     "-l", label, "--no-headers", check=False)
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    return len(lines)


def get_pod_resources(kubeconfig: str, namespace: str, label: str) -> dict:
    result = kubectl(kubeconfig, "-n", namespace, "top", "pods",
                     "-l", label, "--no-headers", check=False)
    lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    if lines:
        parts = lines[0].split()
        if len(parts) >= 3:
            return {"cpu": parts[1], "memory": parts[2]}
    return {"cpu": "N/A", "memory": "N/A"}


def get_all_pod_resources(kubeconfig: str, namespace: str, label: str) -> list[dict]:
    """Return cpu/memory for ALL pods matching a label (not just the first)."""
    result = kubectl(kubeconfig, "-n", namespace, "top", "pods",
                     "-l", label, "--no-headers", check=False)
    pods = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 3:
            pods.append({"name": parts[0], "cpu": parts[1], "memory": parts[2]})
    return pods


def get_pod_restarts(kubeconfig: str, namespace: str, label: str) -> list[dict]:
    """Return restart count and status for pods matching a label."""
    result = kubectl(kubeconfig, "-n", namespace, "get", "pods",
                     "-l", label,
                     "-o", "jsonpath={range .items[*]}"
                     "{.metadata.name},{.status.containerStatuses[0].restartCount},"
                     "{.status.containerStatuses[0].lastState.terminated.reason}"
                     "{\"\\n\"}{end}",
                     check=False)
    pods = []
    for line in result.stdout.strip().split("\n"):
        parts = line.strip().split(",")
        if len(parts) >= 2 and parts[0]:
            pods.append({
                "name": parts[0],
                "restarts": int(parts[1]) if parts[1].isdigit() else 0,
                "last_termination_reason": parts[2] if len(parts) > 2 else "",
            })
    return pods


def sample_resource_usage(cp_kubeconfig: str, dp_kubeconfig: str,
                          namespace: str) -> dict:
    """Take a single resource usage snapshot from both clusters."""
    ts = time.time()
    sample = {"timestamp": ts}

    for component, kc, label in [
        ("vmagent", cp_kubeconfig, "app=vmagent"),
        ("konnectivity_server", cp_kubeconfig, "app=konnectivity-server"),
        ("konnectivity_agent", dp_kubeconfig, "app=konnectivity-agent"),
    ]:
        pods = get_all_pod_resources(kc, namespace, label)
        sample[component] = pods

    return sample


def _classify_targets(active: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split active targets into (load_test_targets, infra_targets).

    Infrastructure targets (konnectivity, vmagent, vmsingle, etc.) are
    separated so they don't count toward the scrape success rate.
    """
    infra_jobs = {
        "konnectivity-server", "konnectivity-agent", "vmagent-self", "vmsingle"
    }
    load, infra = [], []
    for t in active:
        job = t.get("labels", {}).get("job", "")
        if job in infra_jobs:
            infra.append(t)
        else:
            load.append(t)
    return load, infra


def _log_target_summary(active: list[dict]) -> None:
    """Log discovered targets grouped by job name."""
    from collections import defaultdict
    by_job: dict[str, list[str]] = defaultdict(list)
    for t in active:
        job = t.get("labels", {}).get("job", "unknown")
        health = t.get("health", "?")
        addr = t.get("labels", {}).get("instance", t.get("scrapeUrl", "?"))
        by_job[job].append(f"{addr}({health})")
    log.info("  --- Discovered targets by job ---")
    for job in sorted(by_job):
        targets = by_job[job]
        up_count = sum(1 for t in targets if "(up)" in t)
        # Show addresses for small groups, just counts for large ones
        if len(targets) <= 5:
            log.info("    %s [%d/%d]: %s", job, up_count, len(targets), ", ".join(targets))
        else:
            down = [t for t in targets if "(up)" not in t]
            down_str = f" — down: {', '.join(down[:5])}" if down else ""
            log.info("    %s [%d/%d]%s", job, up_count, len(targets), down_str)


def _normalize_error(err: str) -> str:
    """Collapse variable parts of scrape errors so identical root causes group together.

    Strips node names, IP addresses, and port numbers from error messages
    so that e.g. 150 NPD "502 Bad Gateway" errors become one group.
    """
    # Strip scrape URL: "...scraping \"https://...vmss000001:20257/proxy/metrics\": 503..."
    # → "...scraping <url>: 503..."
    err = re.sub(r'scraping "https?://[^"]*"', 'scraping <url>', err)
    # Strip "dialing <ip>:<port>" → "dialing <ip:port>"
    err = re.sub(r'dialing \d+\.\d+\.\d+\.\d+:\d+', 'dialing <ip:port>', err)
    # Strip response body JSON (verbose, always the same structure)
    err = re.sub(r'response body: ".*"', 'response body: <...>', err)
    return err.strip()


def _log_down_target_errors(active: list[dict]) -> None:
    """Log lastError for every down target, grouped by (job, normalized error)."""
    from collections import defaultdict
    down_targets = [t for t in active if t.get("health") != "up"]
    if not down_targets:
        return
    log.warning("  --- %d targets DOWN — error details ---", len(down_targets))
    # Group by (job, normalized_error) so identical root causes collapse
    by_error: dict[tuple[str, str], list[str]] = defaultdict(list)
    for t in down_targets:
        job = t.get("labels", {}).get("job", "unknown")
        err = t.get("lastError", "") or "(no error recorded)"
        normalized = _normalize_error(err)
        addr = t.get("labels", {}).get("instance", t.get("scrapeUrl", "?"))
        by_error[(job, normalized)].append(addr)
    for (job, err), addrs in sorted(by_error.items()):
        sample = ", ".join(addrs[:5])
        suffix = f" (+{len(addrs)-5} more)" if len(addrs) > 5 else ""
        log.warning("    [%s] %d targets: %s", job, len(addrs), err)
        log.warning("      e.g. %s%s", sample, suffix)


def _log_konnectivity_connections(cp_kubeconfig: str, namespace: str) -> None:
    """Log konnectivity-server connection stats from its /metrics endpoint."""
    try:
        with PortForward(cp_kubeconfig, namespace, "deployment/konnectivity-server", 8095, 18095) as pf:
            resp = retry_request(f"{pf.url}/metrics")
            text = resp.text
            ready = extract_prom_value(text, r"^konnectivity_network_proxy_server_ready_backend_connections\s")
            established = extract_prom_value(text, r"^konnectivity_network_proxy_server_established_connections\s")
            grpc = extract_prom_value(text, r'^konnectivity_network_proxy_server_grpc_connections\{')
            pending = extract_prom_value(text, r"^konnectivity_network_proxy_server_pending_backend_dials\s")
            log.warning("  --- Konnectivity server connections ---")
            log.warning("    ready_backend: %d, established: %d, grpc: %d, pending_dials: %d",
                        int(ready), int(established), int(grpc), int(pending))
    except Exception as e:
        log.warning("  Could not fetch konnectivity server metrics: %s", e)


def wait_for_targets(cp_kubeconfig: str, dp_kubeconfig: str, namespace: str,
                     expected: int, timeout_minutes: int,
                     poll_interval: int = 5,
                     stable_rounds: int = 3) -> tuple[int, int, list[dict]]:
    """Wait for all discovered scrape targets to be healthy.

    Instead of requiring a pre-calculated target count, this waits until
    all discovered load-test targets report ``health == "up"`` and the
    count has been stable for ``stable_rounds`` consecutive polls.

    The ``expected`` parameter is used only as a minimum floor — if fewer
    targets are discovered, we keep waiting.  Infrastructure targets
    (konnectivity-server, konnectivity-agent, vmagent-self, vmsingle)
    are excluded from the count.

    Returns (up, total, resource_samples).
    """
    deadline = time.time() + timeout_minutes * 60
    up, total = 0, 0
    active = []
    resource_samples: list[dict] = []
    consecutive_stable = 0
    prev_up, prev_total = 0, 0
    while time.time() < deadline:
        try:
            with PortForward(cp_kubeconfig, namespace, "vmagent-0", 8429, 18429) as pf:
                resp = retry_request(f"{pf.url}/api/v1/targets")
                data = resp.json()
                active = data.get("data", {}).get("activeTargets", [])
                load_targets, _infra = _classify_targets(active)
                up = sum(1 for t in load_targets if t.get("health") == "up")
                total = len(load_targets)
        except Exception as e:
            log.warning("Target poll failed: %s — will retry", e)

        # Sample resource usage alongside each target poll
        try:
            sample = sample_resource_usage(cp_kubeconfig, dp_kubeconfig, namespace)
            sample["targets_up"] = up
            resource_samples.append(sample)
        except Exception as e:
            log.debug("Resource sample failed: %s", e)

        # Check stability: up count meets the expected floor and is unchanged.
        # Rate is reported against `expected` (not `total`) because the scrape
        # config may discover phantom targets (e.g. NPD job with no pods) that
        # would otherwise mask a healthy run.
        rate = up / expected if expected > 0 else 0.0
        if up >= expected and up == prev_up and total == prev_total:
            consecutive_stable += 1
        else:
            consecutive_stable = 0
        prev_up, prev_total = up, total

        log.info("  targets: %d/%d up (%.1f%% of min, min %d, stable %d/%d)",
                 up, total, rate * 100, expected, consecutive_stable, stable_rounds)
        if consecutive_stable >= stable_rounds:
            _log_target_summary(active)
            return up, total, resource_samples
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))
    log.warning("Timed out waiting for targets: %d/%d up after %dm", up, total, timeout_minutes)
    _log_target_summary(active)
    _log_down_target_errors(active)
    _log_konnectivity_connections(cp_kubeconfig, namespace)
    return up, total, resource_samples


def collect_metrics(cp_kubeconfig: str, dp_kubeconfig: str,
                    namespace: str, tier: int, work_dir: Path) -> dict:
    log.info("Collecting metrics from all components...")
    measurements = {}

    # --- Pod counts ---
    measurements["konnectivity_server_pods"] = count_pods(cp_kubeconfig, namespace, "app=konnectivity-server")
    measurements["konnectivity_agent_pods"] = count_pods(dp_kubeconfig, namespace, "app=konnectivity-agent")
    measurements["vmagent_pods"] = count_pods(cp_kubeconfig, namespace, "app=vmagent")
    measurements["fake_exporter_pods"] = sum(
        count_pods(dp_kubeconfig, FAKE_EXPORTER_NS, f"app={app}")
        for _, app, _ in FAKE_EXPORTER_ROLES
    )

    # --- VMAgent targets (scrape health) ---
    try:
        with PortForward(cp_kubeconfig, namespace, "vmagent-0", 8429, 18429) as pf:
            targets_resp = retry_request(f"{pf.url}/api/v1/targets")
            targets_data = targets_resp.json()
            active = targets_data.get("data", {}).get("activeTargets", [])
            load_targets, infra_targets = _classify_targets(active)
            scrape_up = sum(1 for t in load_targets if t.get("health") == "up")
            scrape_total = len(load_targets)
            infra_up = sum(1 for t in infra_targets if t.get("health") == "up")
            infra_total = len(infra_targets)

            raw_dir = work_dir / "raw" / namespace
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "vmagent_targets.json").write_text(json.dumps(targets_data, indent=2))
    except Exception as e:
        log.warning("Failed to collect VMAgent targets: %s", e)
        scrape_up = 0
        scrape_total = 0
        infra_up = 0
        infra_total = 0

    measurements["scrape_targets_up"] = scrape_up
    measurements["scrape_targets_total"] = scrape_total
    measurements["scrape_success_rate"] = (
        round(scrape_up / scrape_total, 4) if scrape_total > 0 else 0.0
    )
    # Infrastructure targets tracked separately (not in pass/fail)
    measurements["infra_targets_up"] = infra_up
    measurements["infra_targets_total"] = infra_total
    measurements["infra_success_rate"] = (
        round(infra_up / infra_total, 4) if infra_total > 0 else 0.0
    )

    # --- VMAgent self-metrics ---
    try:
        with PortForward(cp_kubeconfig, namespace, "vmagent-0", 8429, 18429) as pf:
            metrics_resp = retry_request(f"{pf.url}/metrics")
            vmagent_metrics = metrics_resp.text

            raw_dir = work_dir / "raw" / namespace
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "vmagent_metrics.txt").write_text(vmagent_metrics)

            measurements["vmagent_goroutines"] = extract_prom_value(vmagent_metrics, r"^go_goroutines\s")
            dur_sum = extract_prom_value(vmagent_metrics, r"^vm_promscrape_scrape_duration_seconds_sum\s")
            dur_count = extract_prom_value(vmagent_metrics, r"^vm_promscrape_scrape_duration_seconds_count\s")
            measurements["vmagent_scrape_duration_sum_seconds"] = dur_sum
            measurements["vmagent_scrape_duration_count"] = dur_count
            measurements["vmagent_scrape_duration_mean_seconds"] = (
                round(dur_sum / dur_count, 6) if dur_count > 0 else 0.0
            )
            measurements["vmagent_scrapes_total"] = extract_prom_value(
                vmagent_metrics, r"^vm_promscrape_scrapes_total\s"
            )
            measurements["vmagent_scrapes_failed"] = extract_prom_value(
                vmagent_metrics, r"^vm_promscrape_scrapes_failed_total\s"
            )
            measurements["vmagent_samples_scraped"] = extract_prom_value(
                vmagent_metrics, r"^vm_promscrape_scraped_samples_sum\s"
            )
            measurements["vmagent_samples_post_relabeling"] = extract_prom_value(
                vmagent_metrics, r"^vm_promscrape_samples_post_relabeling_sum\s"
            )
            measurements["vmagent_tcpdialer_dials_total"] = extract_prom_value(
                vmagent_metrics, r"^vm_tcpdialer_dials_total\s"
            )
            tcpdial_sum = extract_prom_value(vmagent_metrics, r"^vm_tcpdialer_dial_duration_seconds_sum\s")
            tcpdial_count = extract_prom_value(vmagent_metrics, r"^vm_tcpdialer_dial_duration_seconds_count\s")
            measurements["vmagent_tcpdialer_dial_sum_seconds"] = tcpdial_sum
            measurements["vmagent_tcpdialer_dial_count"] = tcpdial_count
            measurements["vmagent_tcpdialer_dial_mean_seconds"] = (
                round(tcpdial_sum / tcpdial_count, 6) if tcpdial_count > 0 else 0.0
            )
            measurements["vmagent_resident_memory_bytes"] = extract_prom_value(
                vmagent_metrics, r"^process_resident_memory_bytes\s"
            )
    except Exception as e:
        log.warning("Failed to collect VMAgent self-metrics: %s", e)
        for key in ["vmagent_goroutines", "vmagent_scrape_duration_sum_seconds",
                    "vmagent_scrape_duration_count", "vmagent_scrape_duration_mean_seconds",
                    "vmagent_scrapes_total", "vmagent_scrapes_failed",
                    "vmagent_samples_scraped", "vmagent_samples_post_relabeling",
                    "vmagent_tcpdialer_dials_total", "vmagent_tcpdialer_dial_sum_seconds",
                    "vmagent_tcpdialer_dial_count", "vmagent_tcpdialer_dial_mean_seconds",
                    "vmagent_resident_memory_bytes"]:
            measurements.setdefault(key, 0)

    # --- Konnectivity server metrics (port 8095) ---
    try:
        with PortForward(cp_kubeconfig, namespace, "deployment/konnectivity-server", 8095, 18095) as pf:
            konn_resp = retry_request(f"{pf.url}/metrics")
            konn_metrics = konn_resp.text

            raw_dir = work_dir / "raw" / namespace
            (raw_dir / "konn_server_metrics.txt").write_text(konn_metrics)

            measurements["konn_server_goroutines"] = extract_prom_value(konn_metrics, r"^go_goroutines\s")

            dial_sum = extract_prom_value(konn_metrics, r"^konnectivity_network_proxy_server_dial_duration_seconds_sum\s")
            dial_count = extract_prom_value(konn_metrics, r"^konnectivity_network_proxy_server_dial_duration_seconds_count\s")
            measurements["konn_server_dial_count"] = dial_count
            measurements["konn_server_dial_sum_seconds"] = dial_sum
            measurements["konn_server_dial_mean_seconds"] = (
                round(dial_sum / dial_count, 6) if dial_count > 0 else 0.0
            )

            measurements["konn_server_grpc_connections"] = extract_prom_value(
                konn_metrics, r'^konnectivity_network_proxy_server_grpc_connections\{')
            measurements["konn_server_ready_backend_connections"] = extract_prom_value(
                konn_metrics, r"^konnectivity_network_proxy_server_ready_backend_connections\s")
            measurements["konn_server_established_connections"] = extract_prom_value(
                konn_metrics, r"^konnectivity_network_proxy_server_established_connections\s")
            measurements["konn_server_http_connections"] = extract_prom_value(
                konn_metrics, r"^konnectivity_network_proxy_server_http_connections\s")
            measurements["konn_server_pending_dials"] = extract_prom_value(
                konn_metrics, r"^konnectivity_network_proxy_server_pending_backend_dials\s")

            measurements["konn_server_stream_packets_total"] = extract_prom_sum(
                konn_metrics, r"^konnectivity_network_proxy_server_stream_packets_total\{")
            measurements["konn_server_dial_req_total"] = extract_prom_value(
                konn_metrics, r'konnectivity_network_proxy_server_stream_packets_total\{packet_type="DIAL_REQ"')
            measurements["konn_server_dial_rsp_total"] = extract_prom_value(
                konn_metrics, r'konnectivity_network_proxy_server_stream_packets_total\{packet_type="DIAL_RSP"')
            measurements["konn_server_data_from_agent"] = extract_prom_value(
                konn_metrics, r'konnectivity_network_proxy_server_stream_packets_total\{packet_type="DATA",segment="from_agent"')
            measurements["konn_server_data_to_agent"] = extract_prom_value(
                konn_metrics, r'konnectivity_network_proxy_server_stream_packets_total\{packet_type="DATA",segment="to_agent"')
            measurements["konn_server_close_req_total"] = extract_prom_value(
                konn_metrics, r'konnectivity_network_proxy_server_stream_packets_total\{packet_type="CLOSE_REQ"')
            measurements["konn_server_close_rsp_total"] = extract_prom_value(
                konn_metrics, r'konnectivity_network_proxy_server_stream_packets_total\{packet_type="CLOSE_RSP"')

            measurements["konn_server_stream_errors_total"] = extract_prom_sum(
                konn_metrics, r"^konnectivity_network_proxy_server_stream_errors_total\{")

            fw_sum = extract_prom_value(konn_metrics, r"^konnectivity_network_proxy_server_frontend_write_duration_seconds_sum\s")
            fw_count = extract_prom_value(konn_metrics, r"^konnectivity_network_proxy_server_frontend_write_duration_seconds_count\s")
            measurements["konn_server_frontend_write_count"] = fw_count
            measurements["konn_server_frontend_write_mean_seconds"] = (
                round(fw_sum / fw_count, 6) if fw_count > 0 else 0.0
            )

            # --- Histogram percentiles (p50/p90/p99) ---
            dial_hist = extract_histogram_percentiles(
                konn_metrics, "konnectivity_network_proxy_server_dial_duration_seconds")
            measurements["konn_server_dial_p50_seconds"] = dial_hist["p50"]
            measurements["konn_server_dial_p90_seconds"] = dial_hist["p90"]
            measurements["konn_server_dial_p99_seconds"] = dial_hist["p99"]

            fw_hist = extract_histogram_percentiles(
                konn_metrics, "konnectivity_network_proxy_server_frontend_write_duration_seconds")
            measurements["konn_server_frontend_write_p50_seconds"] = fw_hist["p50"]
            measurements["konn_server_frontend_write_p90_seconds"] = fw_hist["p90"]
            measurements["konn_server_frontend_write_p99_seconds"] = fw_hist["p99"]

            endpoint_hist = extract_histogram_percentiles(
                konn_metrics, "konnectivity_network_proxy_server_endpoint_dial_duration_seconds")
            measurements["konn_server_endpoint_dial_p50_seconds"] = endpoint_hist["p50"]
            measurements["konn_server_endpoint_dial_p90_seconds"] = endpoint_hist["p90"]
            measurements["konn_server_endpoint_dial_p99_seconds"] = endpoint_hist["p99"]
            measurements["konn_server_endpoint_dial_mean_seconds"] = endpoint_hist["mean"]
            measurements["konn_server_endpoint_dial_count"] = endpoint_hist["count"]

            # --- Byte counters ---
            measurements["konn_server_frontend_write_bytes_total"] = extract_prom_value(
                konn_metrics, r"^konnectivity_network_proxy_server_frontend_write_bytes_total\s")
            measurements["konn_server_frontend_read_bytes_total"] = extract_prom_value(
                konn_metrics, r"^konnectivity_network_proxy_server_frontend_read_bytes_total\s")

            # --- Dial failures ---
            measurements["konn_server_dial_failure_count"] = extract_prom_value(
                konn_metrics, r"^konnectivity_network_proxy_server_dial_failure_count\s")

            # --- Process CPU (for rate calculation across tiers) ---
            measurements["konn_server_process_cpu_seconds_total"] = extract_prom_value(
                konn_metrics, r"^process_cpu_seconds_total\s")
            measurements["konn_server_resident_memory_bytes"] = extract_prom_value(
                konn_metrics, r"^process_resident_memory_bytes\s")

    except Exception as e:
        log.warning("Failed to collect konnectivity-server metrics: %s", e)
        for key in ["konn_server_goroutines", "konn_server_dial_count",
                    "konn_server_dial_sum_seconds", "konn_server_dial_mean_seconds",
                    "konn_server_grpc_connections", "konn_server_ready_backend_connections",
                    "konn_server_established_connections", "konn_server_http_connections",
                    "konn_server_pending_dials", "konn_server_stream_packets_total",
                    "konn_server_dial_req_total", "konn_server_dial_rsp_total",
                    "konn_server_data_from_agent", "konn_server_data_to_agent",
                    "konn_server_close_req_total", "konn_server_close_rsp_total",
                    "konn_server_stream_errors_total", "konn_server_frontend_write_count",
                    "konn_server_frontend_write_mean_seconds",
                    "konn_server_dial_p50_seconds", "konn_server_dial_p90_seconds",
                    "konn_server_dial_p99_seconds",
                    "konn_server_frontend_write_p50_seconds",
                    "konn_server_frontend_write_p90_seconds",
                    "konn_server_frontend_write_p99_seconds",
                    "konn_server_endpoint_dial_p50_seconds",
                    "konn_server_endpoint_dial_p90_seconds",
                    "konn_server_endpoint_dial_p99_seconds",
                    "konn_server_endpoint_dial_mean_seconds",
                    "konn_server_endpoint_dial_count",
                    "konn_server_frontend_write_bytes_total",
                    "konn_server_frontend_read_bytes_total",
                    "konn_server_dial_failure_count",
                    "konn_server_process_cpu_seconds_total",
                    "konn_server_resident_memory_bytes"]:
            measurements.setdefault(key, 0)

    # --- Konnectivity agent metrics (via vmsingle — DP port-forward unreliable) ---
    try:
        with PortForward(cp_kubeconfig, namespace, "deployment/vmsingle", 8428, 18428) as pf:
            # Quick health check — fail fast if vmsingle is down
            retry_request(f"{pf.url}/health", retries=1, backoff=1)
            vm_url = f"{pf.url}/api/v1/query"

            agent_queries = {
                "konn_agent_goroutines":
                    'sum(go_goroutines{job="konnectivity-agent"})',
                "konn_agent_open_server_connections":
                    'sum(konnectivity_network_proxy_agent_open_server_connections{job="konnectivity-agent"})',
                "konn_agent_open_endpoint_connections":
                    'sum(konnectivity_network_proxy_agent_open_endpoint_connections{job="konnectivity-agent"})',
                "konn_agent_server_connection_failures":
                    'sum(konnectivity_network_proxy_agent_server_connection_failure_count{job="konnectivity-agent"})',
                "konn_agent_endpoint_dial_failures":
                    'sum(konnectivity_network_proxy_agent_endpoint_dial_failure_count{job="konnectivity-agent"})',
                "konn_agent_stream_packets_total":
                    'sum(konnectivity_network_proxy_agent_stream_packets_total{job="konnectivity-agent"})',
                "konn_agent_stream_errors_total":
                    'sum(konnectivity_network_proxy_agent_stream_errors_total{job="konnectivity-agent"})',
                "konn_agent_process_cpu_seconds_total":
                    'sum(process_cpu_seconds_total{job="konnectivity-agent"})',
                "konn_agent_resident_memory_bytes":
                    'sum(process_resident_memory_bytes{job="konnectivity-agent"})',
            }
            for key, query in agent_queries.items():
                try:
                    resp = retry_request(vm_url, params={"query": query})
                    result = resp.json().get("data", {}).get("result", [])
                    measurements[key] = float(result[0]["value"][1]) if result else 0
                except Exception:
                    measurements[key] = 0

    except Exception as e:
        log.warning("Failed to collect konnectivity-agent metrics from vmsingle: %s", e)
        for key in ["konn_agent_goroutines", "konn_agent_open_server_connections",
                    "konn_agent_open_endpoint_connections",
                    "konn_agent_server_connection_failures",
                    "konn_agent_endpoint_dial_failures",
                    "konn_agent_stream_packets_total",
                    "konn_agent_stream_errors_total",
                    "konn_agent_process_cpu_seconds_total",
                    "konn_agent_resident_memory_bytes"]:
            measurements.setdefault(key, 0)

    # --- Resource usage (final snapshot) ---
    konn_res = get_pod_resources(cp_kubeconfig, namespace, "app=konnectivity-server")
    measurements["konn_server_cpu"] = konn_res["cpu"]
    measurements["konn_server_memory"] = konn_res["memory"]

    vmagent_res = get_pod_resources(cp_kubeconfig, namespace, "app=vmagent")
    measurements["vmagent_cpu"] = vmagent_res["cpu"]
    measurements["vmagent_memory"] = vmagent_res["memory"]

    konn_agent_res = get_all_pod_resources(dp_kubeconfig, namespace, "app=konnectivity-agent")
    measurements["konn_agent_resources"] = konn_agent_res

    # --- Pod restarts + OOM on both clusters ---
    total_restarts = 0
    total_ooms = 0
    restart_details = {}
    for label, name, kc in [
        ("app=konnectivity-server", "konn_server", cp_kubeconfig),
        ("app=vmagent", "vmagent", cp_kubeconfig),
        ("app=konnectivity-agent", "konn_agent", dp_kubeconfig),
    ]:
        pods = get_pod_restarts(kc, namespace, label)
        restarts = sum(p["restarts"] for p in pods)
        ooms = sum(1 for p in pods if p["last_termination_reason"] == "OOMKilled")
        total_restarts += restarts
        total_ooms += ooms
        restart_details[name] = pods
    measurements["pod_restarts_total"] = total_restarts
    measurements["pod_oom_killed"] = total_ooms
    measurements["pod_restart_details"] = restart_details

    # --- OOM events (both clusters) ---
    oom_events = 0
    for kc in [cp_kubeconfig, dp_kubeconfig]:
        result = kubectl(kc, "-n", namespace, "get", "events",
                         "--field-selector", "reason=OOMKilled", "--no-headers", check=False)
        oom_lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        oom_events += len(oom_lines)
    measurements["oom_events"] = oom_events

    # --- Container CPU/memory from vmsingle (cadvisor data for DP pods) ---
    try:
        with PortForward(cp_kubeconfig, namespace, "deployment/vmsingle", 8428, 18428) as pf:
            retry_request(f"{pf.url}/health", retries=1, backoff=1)
            container_metrics = {}
            for container, query in [
                ("konnectivity_agent_cpu_rate",
                 'sum(rate(container_cpu_usage_seconds_total{namespace="' + namespace + '",container="konnectivity-agent"}[2m])) by (pod)'),
                ("konnectivity_agent_memory",
                 'sum(container_memory_working_set_bytes{namespace="' + namespace + '",container="konnectivity-agent"}) by (pod)'),
            ]:
                try:
                    resp = retry_request(f"{pf.url}/api/v1/query", params={"query": query})
                    data = resp.json().get("data", {}).get("result", [])
                    container_metrics[container] = [
                        {"pod": r["metric"].get("pod", "?"), "value": r["value"][1]}
                        for r in data
                    ]
                except Exception:
                    container_metrics[container] = []
            measurements["dp_container_metrics"] = container_metrics
    except Exception as e:
        log.debug("Failed to query vmsingle for container metrics: %s", e)
        measurements["dp_container_metrics"] = {}

    # --- vmsingle write-path metrics ---
    try:
        with PortForward(cp_kubeconfig, namespace, "deployment/vmsingle", 8428, 18428) as pf:
            retry_request(f"{pf.url}/health", retries=1, backoff=1)
            vm_resp = retry_request(f"{pf.url}/metrics")
            vm_metrics = vm_resp.text

            raw_dir = work_dir / "raw" / namespace
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "vmsingle_metrics.txt").write_text(vm_metrics)

            measurements["vmsingle_rows_inserted"] = extract_prom_value(
                vm_metrics, r'^vm_rows_inserted_total{type="promremotewrite"}'
            )
            measurements["vmsingle_http_requests_total"] = extract_prom_value(
                vm_metrics, r'^vm_http_requests_total{path="/api/v1/write"'
            )
            measurements["vmsingle_http_errors_total"] = extract_prom_value(
                vm_metrics, r'^vm_http_errors_total{path="/api/v1/write"'
            )
            measurements["vmsingle_series_created"] = extract_prom_value(
                vm_metrics, r'^vm_new_timeseries_created_total\s'
            )

            query_resp = retry_request(
                f"{pf.url}/api/v1/query?query=count(up)"
            )
            query_data = query_resp.json()
            result_vec = query_data.get("data", {}).get("result", [])
            if result_vec:
                measurements["vmsingle_series_up_count"] = int(float(result_vec[0].get("value", [0, 0])[1]))
            else:
                measurements["vmsingle_series_up_count"] = 0
    except Exception as e:
        log.warning("Failed to collect vmsingle metrics: %s", e)
        for key in ["vmsingle_rows_inserted", "vmsingle_http_requests_total",
                    "vmsingle_http_errors_total", "vmsingle_series_created",
                    "vmsingle_series_up_count"]:
            measurements.setdefault(key, 0)

    # --- Infrastructure time-series from vmsingle (from self-monitoring scrape jobs) ---
    try:
        with PortForward(cp_kubeconfig, namespace, "deployment/vmsingle", 8428, 18428) as pf:
            retry_request(f"{pf.url}/health", retries=1, backoff=1)

            def _query_instant(q: str):
                """Run PromQL instant query, return first scalar or None."""
                try:
                    r = retry_request(f"{pf.url}/api/v1/query", params={"query": q})
                    results = r.json().get("data", {}).get("result", [])
                    if results:
                        return float(results[0].get("value", [0, None])[1])
                except Exception:
                    pass
                return None

            # Konn-server CPU rate (from self-monitoring job)
            measurements["konn_server_cpu_rate"] = _query_instant(
                'rate(process_cpu_seconds_total{job="konnectivity-server"}[2m])')

            # Konn-server dial rate (dials per second over last 2m)
            measurements["konn_server_dial_rate"] = _query_instant(
                'rate(konnectivity_network_proxy_server_dial_duration_seconds_count{job="konnectivity-server"}[2m])')

            # Konn-server stream packet rate
            measurements["konn_server_stream_packet_rate"] = _query_instant(
                'sum(rate(konnectivity_network_proxy_server_stream_packets_total{job="konnectivity-server"}[2m]))')

            # Konn-server frontend write rate
            measurements["konn_server_frontend_write_rate"] = _query_instant(
                'rate(konnectivity_network_proxy_server_frontend_write_duration_seconds_count{job="konnectivity-server"}[2m])')

            # Konn-server byte throughput rate (bytes/sec)
            measurements["konn_server_write_bytes_rate"] = _query_instant(
                'rate(konnectivity_network_proxy_server_frontend_write_bytes_total{job="konnectivity-server"}[2m])')
            measurements["konn_server_read_bytes_rate"] = _query_instant(
                'rate(konnectivity_network_proxy_server_frontend_read_bytes_total{job="konnectivity-server"}[2m])')

            # VMAgent scrape duration (average over last 2m)
            measurements["vmagent_scrape_duration_mean"] = _query_instant(
                'avg(scrape_duration_seconds{job=~"fake-.*|real-.*"})')
            measurements["vmagent_scrape_samples_rate"] = _query_instant(
                'sum(rate(scrape_samples_scraped{job=~"fake-.*|real-.*"}[2m]))')

            # Konn-agent aggregate metrics (across all agent pods)
            measurements["konn_agent_total_server_connections"] = _query_instant(
                'sum(konnectivity_network_proxy_agent_open_server_connections{job="konnectivity-agent"})')
            measurements["konn_agent_total_endpoint_connections"] = _query_instant(
                'sum(konnectivity_network_proxy_agent_open_endpoint_connections{job="konnectivity-agent"})')
            measurements["konn_agent_total_stream_packet_rate"] = _query_instant(
                'sum(rate(konnectivity_network_proxy_agent_stream_packets_total{job="konnectivity-agent"}[2m]))')
            measurements["konn_agent_total_stream_errors"] = _query_instant(
                'sum(konnectivity_network_proxy_agent_stream_errors_total{job="konnectivity-agent"})')
            measurements["konn_agent_cpu_rate"] = _query_instant(
                'sum(rate(process_cpu_seconds_total{job="konnectivity-agent"}[2m]))')

            log.info("  infra time-series: konn_cpu_rate=%s dial_rate=%s stream_pkt_rate=%s agent_conns=%s",
                     measurements.get("konn_server_cpu_rate"),
                     measurements.get("konn_server_dial_rate"),
                     measurements.get("konn_server_stream_packet_rate"),
                     measurements.get("konn_agent_total_server_connections"))
    except Exception as e:
        log.debug("Failed to query infrastructure time-series from vmsingle: %s", e)

    log.info("  scrape=%d/%d (%.4f), konn_dial_mean=%.6fs, oom=%d, restarts=%d, rw_rows=%.0f, rw_series_up=%d",
             scrape_up, scrape_total, measurements["scrape_success_rate"],
             measurements.get("konn_server_dial_mean_seconds", 0),
             measurements["oom_events"] + measurements["pod_oom_killed"],
             measurements["pod_restarts_total"],
             measurements.get("vmsingle_rows_inserted", 0),
             measurements.get("vmsingle_series_up_count", 0))
    log.info("  konn: grpc=%d ready=%d established=%d pending=%d dials=%d stream_pkts=%.0f stream_errs=%.0f",
             measurements.get("konn_server_grpc_connections", 0),
             measurements.get("konn_server_ready_backend_connections", 0),
             measurements.get("konn_server_established_connections", 0),
             measurements.get("konn_server_pending_dials", 0),
             measurements.get("konn_server_dial_count", 0),
             measurements.get("konn_server_stream_packets_total", 0),
             measurements.get("konn_server_stream_errors_total", 0))

    return measurements


def evaluate_pass_fail(measurements: dict, expected_targets: int = 0) -> dict:
    scrape_up = measurements.get("scrape_targets_up", 0)
    scrape_total = measurements.get("scrape_targets_total", 0)
    scrape_rate = measurements.get("scrape_success_rate", 0)
    oom_events = measurements.get("oom_events", 0)
    oom_killed = measurements.get("pod_oom_killed", 0)
    restarts = measurements.get("pod_restarts_total", 0)
    dial_mean = measurements.get("konn_server_dial_mean_seconds", 0)
    rw_errors = measurements.get("vmsingle_http_errors_total", 0)
    rw_rows = measurements.get("vmsingle_rows_inserted", 0)
    dial_failures = measurements.get("konn_server_dial_failure_count", 0)
    stream_errors = measurements.get("konn_server_stream_errors_total", 0)
    stream_packets = measurements.get("konn_server_stream_packets_total", 0)
    agent_dial_failures = measurements.get("konn_agent_endpoint_dial_failures", 0)

    # If expected_targets is set, pass when up >= expected (other SD-discovered
    # targets like DaemonSet services may not be running on the test cluster).
    # Otherwise fall back to the overall up/total rate.
    if expected_targets > 0:
        scrape_pass = scrape_up >= expected_targets
    else:
        scrape_pass = scrape_rate >= 0.99
    oom_pass = (oom_events + oom_killed) == 0
    restarts_pass = restarts == 0
    dial_pass = dial_mean < 2.0
    rw_errors_pass = rw_errors == 0
    rw_rows_pass = rw_rows > 0
    dial_failures_pass = dial_failures == 0
    # Stream errors are normal connection lifecycle events (close/reset).
    # Use error *rate* (errors / packets) instead of absolute count;
    # a rate above 10% indicates a real problem.
    stream_error_rate = stream_errors / stream_packets if stream_packets > 0 else 0.0
    stream_errors_pass = stream_error_rate < 0.10
    agent_dial_pass = agent_dial_failures == 0
    overall = (scrape_pass and oom_pass and restarts_pass and dial_pass
               and rw_errors_pass and rw_rows_pass and dial_failures_pass
               and stream_errors_pass and agent_dial_pass)

    def _r(b): return "success" if b else "failure"

    return {
        "scrape_targets": {
            "expected": expected_targets, "up": scrape_up,
            "total_discovered": scrape_total, "rate": scrape_rate, "result": _r(scrape_pass),
        },
        "oom_events": {"threshold": 0, "actual": oom_events + oom_killed, "result": _r(oom_pass)},
        "pod_restarts": {"threshold": 0, "actual": restarts, "result": _r(restarts_pass)},
        "konn_dial_mean_seconds": {"threshold": 2.0, "actual": dial_mean, "result": _r(dial_pass)},
        "konn_dial_failures": {"threshold": 0, "actual": dial_failures, "result": _r(dial_failures_pass)},
        "konn_stream_error_rate": {"threshold": "<10%", "actual": round(stream_error_rate, 4),
                                   "detail": f"{stream_errors:.0f}/{stream_packets:.0f} packets",
                                   "result": _r(stream_errors_pass)},
        "konn_agent_dial_failures": {"threshold": 0, "actual": agent_dial_failures, "result": _r(agent_dial_pass)},
        "remote_write_errors": {"threshold": 0, "actual": rw_errors, "result": _r(rw_errors_pass)},
        "remote_write_rows_inserted": {"threshold": ">0", "actual": rw_rows, "result": _r(rw_rows_pass)},
        "overall": _r(overall),
    }


def _parse_pprof_top(raw: str) -> dict:
    """Parse 'go tool pprof -top' output into structured data."""
    lines = raw.strip().split("\n")
    result = {"header": "", "total": "", "entries": []}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("Type:") or line.startswith("Time:") or line.startswith("Active"):
            if line.startswith("Type:"):
                result["header"] = line
            continue
        if "total" in line.lower() and ("Showing" in line or "of" in line):
            result["total"] = line
            continue
        # Skip column header line
        if line.startswith("flat"):
            continue
        # Parse data row: flat flat% sum% cum cum% name
        parts = line.split(None, 5)
        if len(parts) >= 6 and "%" in parts[1]:
            result["entries"].append({
                "flat": parts[0], "flat_pct": parts[1],
                "sum_pct": parts[2],
                "cum": parts[3], "cum_pct": parts[4],
                "function": parts[5],
            })
    return result


def analyze_pprof(collected: dict[str, str], top_n: int = 15) -> dict:
    """Run 'go tool pprof -top' on each collected profile and return structured analysis."""
    go_bin = shutil.which("go")
    if not go_bin:
        log.warning("go not found in PATH — skipping pprof analysis")
        return {}

    analysis = {}
    for name, filepath in collected.items():
        if not Path(filepath).exists():
            continue
        try:
            result = subprocess.run(
                [go_bin, "tool", "pprof", "-top", f"-nodecount={top_n}", filepath],
                capture_output=True, text=True, timeout=30,
            )
            raw = result.stdout
            parsed = _parse_pprof_top(raw)

            # Save raw text alongside .pb.gz
            raw_path = Path(filepath).with_suffix(".top.txt")
            raw_path.write_text(raw)

            analysis[name] = {
                "raw_file": str(raw_path),
                "total": parsed["total"],
                "header": parsed["header"],
                "top_functions": parsed["entries"],
            }
            log.info("  %s analysis: %s (%d functions)", name, parsed["total"], len(parsed["entries"]))
        except Exception as e:
            log.warning("  %s analysis failed: %s", name, e)

    # Summarize key indicators
    if "goroutine" in analysis:
        entries = analysis["goroutine"].get("top_functions", [])
        total_str = analysis["goroutine"].get("total", "")
        # Extract total goroutine count from "41 total" or "Showing nodes accounting for 39, 95.12% of 41 total"
        m = re.search(r"of\s+(\d+)\s+total", total_str)
        analysis["goroutine_count"] = int(m.group(1)) if m else 0

    if "heap" in analysis:
        total_str = analysis["heap"].get("total", "")
        analysis["heap_total"] = total_str

    return analysis


def _collect_component_pprof(kubeconfig: str, namespace: str, resource: str,
                             remote_port: int, prefix: str, label: str,
                             pprof_dir: Path, cpu_seconds: int) -> dict:
    """Collect pprof profiles from a single component and return {name: filepath}."""
    profiles = {
        "heap": "/debug/pprof/heap",
        "allocs": "/debug/pprof/allocs",
        "goroutine": "/debug/pprof/goroutine",
        "cpu": f"/debug/pprof/profile?seconds={cpu_seconds}",
    }
    collected = {}
    timeout = cpu_seconds + 15
    local_port = remote_port + 20000  # offset 20000 to avoid collision with metrics ports (18xxx)
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            with PortForward(kubeconfig, namespace, resource, remote_port, local_port) as pf:
                for name, path in profiles.items():
                    filename = f"{prefix}-{name}-{label}.pb.gz"
                    filepath = pprof_dir / filename
                    try:
                        import requests as _req
                        resp = _req.get(f"{pf.url}{path}", timeout=timeout)
                        resp.raise_for_status()
                        filepath.write_bytes(resp.content)
                        collected[name] = str(filepath)
                        log.info("  %s/%s: %s (%d bytes)", prefix, name, filepath, len(resp.content))
                    except Exception as e:
                        log.warning("  %s/%s: FAILED — %s", prefix, name, e)
            break  # success — stop retrying
        except Exception as e:
            if attempt < max_retries:
                log.warning("pprof port-forward failed for %s (attempt %d/%d): %s — retrying in 5s",
                            prefix, attempt, max_retries, e)
                time.sleep(5)
                local_port += 1  # try next port on retry
            else:
                log.warning("pprof collection failed for %s after %d attempts: %s", prefix, max_retries, e)
    return collected


def collect_pprof(cp_kubeconfig: str, dp_kubeconfig: str,
                  namespace: str, work_dir: Path,
                  label: str, cpu_seconds: int = 30) -> dict:
    """Collect pprof profiles from konn-server, konn-agent, and vmagent.

    - konn-server: CP cluster, admin port 8095
    - konn-agent:  DP cluster, admin port 8094 (first pod)
    - vmagent:     CP cluster, HTTP port 8429

    Runs auto-analysis via 'go tool pprof -top'.
    Returns dict keyed by component with 'files' and 'analysis' sub-dicts.
    """
    pprof_dir = work_dir / "pprof" / namespace
    pprof_dir.mkdir(parents=True, exist_ok=True)

    components = {
        "konn_server": {
            "kubeconfig": cp_kubeconfig,
            "resource": "deployment/konnectivity-server",
            "port": 8095,
            "prefix": "konn-server",
        },
        "konn_agent": {
            "kubeconfig": dp_kubeconfig,
            "resource": "deployment/konnectivity-agent",
            "port": 8094,
            "prefix": "konn-agent",
        },
        "vmagent": {
            "kubeconfig": cp_kubeconfig,
            "resource": "statefulset/vmagent",
            "port": 8429,
            "prefix": "vmagent",
        },
    }

    all_results = {}
    for comp_name, cfg in components.items():
        log.info("Collecting pprof profiles from %s (cpu=%ds)...", cfg["prefix"], cpu_seconds)
        collected = _collect_component_pprof(
            kubeconfig=cfg["kubeconfig"],
            namespace=namespace,
            resource=cfg["resource"],
            remote_port=cfg["port"],
            prefix=cfg["prefix"],
            label=label,
            pprof_dir=pprof_dir,
            cpu_seconds=cpu_seconds,
        )
        analysis = analyze_pprof(collected) if collected else {}
        all_results[comp_name] = {"files": collected, "analysis": analysis}

    return all_results


def collect_diagnostics(cp_kubeconfig: str, dp_kubeconfig: str,
                       namespace: str, work_dir: Path,
                       include_fake_exporters: bool = True) -> dict:
    """Collect container logs, events, and pod descriptions for RCA.

    Saves artifacts under ``work_dir / "diagnostics" / namespace /``
    with ``cp/`` and ``dp/`` subdirectories.

    Returns:
        Summary dict with collected file counts per cluster.
    """
    diag_dir = work_dir / "diagnostics" / namespace
    summary: dict = {"cp": {}, "dp": {}}

    clusters = [
        ("cp", cp_kubeconfig, [namespace]),
        ("dp", dp_kubeconfig, [namespace]),
    ]
    if include_fake_exporters:
        # Only collect events/describe for fake-exporter ns, skip per-pod logs
        clusters[1] = ("dp", dp_kubeconfig, [namespace, FAKE_EXPORTER_NS])

    # Namespaces where per-pod logs are worth collecting (skip fake-exporters)
    log_namespaces = {namespace}

    for cluster_label, kubeconfig, namespaces in clusters:
        cluster_dir = diag_dir / cluster_label
        cluster_dir.mkdir(parents=True, exist_ok=True)
        files_collected = 0

        for ns in namespaces:
            ns_dir = cluster_dir / ns
            ns_dir.mkdir(parents=True, exist_ok=True)

            # Kubernetes events
            try:
                result = kubectl(kubeconfig, "-n", ns, "get", "events",
                                 "--sort-by=.lastTimestamp", check=False)
                (ns_dir / "events.txt").write_text(result.stdout or "")
                files_collected += 1
            except Exception as e:
                log.debug("Failed to collect events from %s/%s: %s", cluster_label, ns, e)

            # Pod descriptions
            try:
                result = kubectl(kubeconfig, "-n", ns, "describe", "pods", check=False)
                (ns_dir / "pods-describe.txt").write_text(result.stdout or "")
                files_collected += 1
            except Exception as e:
                log.debug("Failed to describe pods in %s/%s: %s", cluster_label, ns, e)

            # Per-pod container logs (skip for large stateless namespaces like fake-exporter)
            if ns not in log_namespaces:
                log.info("Skipping per-pod logs for %s/%s (%d pods — stateless workload)",
                         cluster_label, ns,
                         len([l for l in (kubectl(kubeconfig, "-n", ns, "get", "pods",
                              "-o", "jsonpath={range .items[*]}{.metadata.name}{\"\\n\"}{end}",
                              check=False).stdout or "").strip().split("\n") if l.strip()]))
                continue
            try:
                result = kubectl(kubeconfig, "-n", ns, "get", "pods",
                                 "-o", "jsonpath={range .items[*]}"
                                 "{.metadata.name},{.status.phase},"
                                 "{range .spec.containers[*]}{.name}{\" \"}{end}"
                                 "{\"\\n\"}{end}",
                                 check=False)
                pod_lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
                total_pods = len(pod_lines)
                for i, line in enumerate(pod_lines, 1):
                    parts = line.strip().split(",")
                    if len(parts) < 3 or not parts[0]:
                        continue
                    pod_name = parts[0]
                    containers = parts[2].strip().split()
                    if i % 10 == 0 or i == total_pods:
                        log.info("  Collecting logs: %s/%s [%d/%d pods]",
                                 cluster_label, ns, i, total_pods)
                    for container in containers:
                        if not container:
                            continue
                        try:
                            lr = kubectl(kubeconfig, "-n", ns, "logs", pod_name,
                                         "-c", container, "--tail=1000", check=False)
                            if lr.stdout and lr.stdout.strip():
                                (ns_dir / f"{pod_name}_{container}.log").write_text(lr.stdout)
                                files_collected += 1
                        except Exception:
                            pass
                        # Previous (crashed) container logs
                        try:
                            lr = kubectl(kubeconfig, "-n", ns, "logs", pod_name,
                                         "-c", container, "--previous", "--tail=500", check=False)
                            if lr.returncode == 0 and lr.stdout and lr.stdout.strip():
                                (ns_dir / f"{pod_name}_{container}.previous.log").write_text(lr.stdout)
                                files_collected += 1
                        except Exception:
                            pass
            except Exception as e:
                log.debug("Failed to collect logs from %s/%s: %s", cluster_label, ns, e)

        summary[cluster_label] = {"files_collected": files_collected, "dir": str(cluster_dir)}

    log.info("Diagnostics collected: cp=%d dp=%d files",
             summary["cp"].get("files_collected", 0),
             summary["dp"].get("files_collected", 0))
    return summary
