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


def wait_for_targets(cp_kubeconfig: str, dp_kubeconfig: str, namespace: str,
                     expected: int, timeout_minutes: int,
                     poll_interval: int = 5) -> tuple[int, int, list[dict]]:
    """Wait for scrape targets and sample resource usage each cycle.

    Returns (up, total, resource_samples).
    """
    deadline = time.time() + timeout_minutes * 60
    up, total = 0, 0
    resource_samples: list[dict] = []
    while time.time() < deadline:
        try:
            with PortForward(cp_kubeconfig, namespace, "vmagent-0", 8429, 18429) as pf:
                resp = retry_request(f"{pf.url}/api/v1/targets")
                data = resp.json()
                active = data.get("data", {}).get("activeTargets", [])
                up = sum(1 for t in active if t.get("health") == "up")
                total = len(active)
        except Exception as e:
            log.warning("Target poll failed: %s — will retry", e)

        # Sample resource usage alongside each target poll
        try:
            sample = sample_resource_usage(cp_kubeconfig, dp_kubeconfig, namespace)
            sample["targets_up"] = up
            resource_samples.append(sample)
        except Exception as e:
            log.debug("Resource sample failed: %s", e)

        log.info("  targets: %d/%d up (need %d)", up, total, expected)
        if up >= expected:
            return up, total, resource_samples
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))
    log.warning("Timed out waiting for targets: %d/%d up after %dm", up, total, timeout_minutes)
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
            scrape_up = sum(1 for t in active if t.get("health") == "up")
            scrape_total = len(active)

            raw_dir = work_dir / "raw" / namespace
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "vmagent_targets.json").write_text(json.dumps(targets_data, indent=2))
    except Exception as e:
        log.warning("Failed to collect VMAgent targets: %s", e)
        scrape_up = 0
        scrape_total = 0

    measurements["scrape_targets_up"] = scrape_up
    measurements["scrape_targets_total"] = scrape_total
    measurements["scrape_success_rate"] = (
        round(scrape_up / scrape_total, 4) if scrape_total > 0 else 0.0
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
                    "konn_server_frontend_write_mean_seconds"]:
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

    if expected_targets > 0:
        scrape_pass = scrape_up >= expected_targets
    else:
        scrape_pass = scrape_rate >= 0.99
    oom_pass = (oom_events + oom_killed) == 0
    restarts_pass = restarts == 0
    dial_pass = dial_mean < 2.0
    rw_errors_pass = rw_errors == 0
    rw_rows_pass = rw_rows > 0
    overall = scrape_pass and oom_pass and restarts_pass and dial_pass and rw_errors_pass and rw_rows_pass

    return {
        "scrape_targets": {"expected": expected_targets, "up": scrape_up, "total_discovered": scrape_total, "rate": scrape_rate, "pass": scrape_pass},
        "oom_events": {"threshold": 0, "actual": oom_events + oom_killed, "pass": oom_pass},
        "pod_restarts": {"threshold": 0, "actual": restarts, "pass": restarts_pass},
        "konn_dial_mean_seconds": {"threshold": 2.0, "actual": dial_mean, "pass": dial_pass},
        "remote_write_errors": {"threshold": 0, "actual": rw_errors, "pass": rw_errors_pass},
        "remote_write_rows_inserted": {"threshold": ">0", "actual": rw_rows, "pass": rw_rows_pass},
        "overall": overall,
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
    local_port = remote_port + 10000  # avoid collisions
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
    except Exception as e:
        log.warning("pprof collection failed for %s (port-forward): %s", prefix, e)
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
