#!/usr/bin/env python3
"""
compare.py — Compare real-node vs fake-exporter (node-exporter) load test results.

Reads two result JSON files (one from --real-targets mode, one from fake mode)
and produces a side-by-side markdown comparison report.

Usage:
  python3 -m vmagent_loadtest.compare \
    --real results/fake-cp-loadtest-...-real-10.json \
    --fake results/fake-cp-loadtest-...-fake-10.json \
    [--output comparison-report.md]
"""

import argparse
import json
import sys
from pathlib import Path


def _fmt(val, unit: str = "", precision: int = 4) -> str:
    """Format a value for display."""
    if val is None:
        return "N/A"
    if isinstance(val, float):
        if unit == "bytes":
            return _fmt_bytes(val)
        return f"{val:.{precision}f}{unit}"
    return str(val)


def _fmt_bytes(b) -> str:
    if b is None or b == 0:
        return "0 B"
    for u in ["B", "KB", "MB", "GB"]:
        if abs(b) < 1024:
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"


def _pct_diff(real_val, fake_val) -> str:
    """Percentage difference: (fake - real) / real × 100."""
    if real_val is None or fake_val is None:
        return "N/A"
    if isinstance(real_val, str) or isinstance(fake_val, str):
        return "—"
    if real_val == 0:
        if fake_val == 0:
            return "0%"
        return "+∞"
    diff = (fake_val - real_val) / abs(real_val) * 100
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.1f}%"


def compare(real: dict, fake: dict) -> str:
    """Generate markdown comparison report."""
    rm = real.get("measurements", {})
    fm = fake.get("measurements", {})

    lines = []
    lines.append("# Comparison: Real Nodes vs Fake Exporter (Node-Exporter)")
    lines.append("")
    lines.append(f"- **Tier**: {real.get('tier', '?')} nodes (real) vs {fake.get('tier', '?')} replicas (fake)")
    lines.append(f"- **Real mode**: {real.get('mode', '?')}")
    lines.append(f"- **Fake mode**: {fake.get('mode', '?')}")
    lines.append(f"- **Real run**: {real.get('run_id', '?')} @ {real.get('timestamp', '?')}")
    lines.append(f"- **Fake run**: {fake.get('run_id', '?')} @ {fake.get('timestamp', '?')}")
    if real.get("dp_node_count"):
        lines.append(f"- **Real DP nodes**: {real['dp_node_count']}")
    lines.append("")

    # --- Scrape Targets ---
    lines.append("## Scrape Targets")
    lines.append("")
    lines.append("| Metric | Real | Fake | Δ% |")
    lines.append("|--------|------|------|----|")
    for key, label in [
        ("scrape_targets_up", "Targets Up"),
        ("scrape_targets_total", "Targets Total"),
        ("scrape_success_rate", "Success Rate"),
        ("infra_targets_up", "Infra Targets Up"),
        ("infra_targets_total", "Infra Targets Total"),
    ]:
        rv, fv = rm.get(key), fm.get(key)
        unit = "" if "rate" not in key else ""
        lines.append(f"| {label} | {_fmt(rv)} | {_fmt(fv)} | {_pct_diff(rv, fv)} |")
    lines.append("")

    # --- VMAgent Performance ---
    lines.append("## VMAgent Performance")
    lines.append("")
    lines.append("| Metric | Real | Fake | Δ% |")
    lines.append("|--------|------|------|----|")
    for key, label, unit in [
        ("vmagent_scrape_duration_mean_seconds", "Scrape Duration (mean)", "s"),
        ("vmagent_scrapes_total", "Total Scrapes", ""),
        ("vmagent_scrapes_failed", "Failed Scrapes", ""),
        ("vmagent_samples_scraped", "Samples Scraped", ""),
        ("vmagent_samples_post_relabeling", "Samples Post-Relabeling", ""),
        ("vmagent_goroutines", "Goroutines", ""),
        ("vmagent_tcpdialer_dial_mean_seconds", "TCP Dial Mean", "s"),
        ("vmagent_tcpdialer_dials_total", "TCP Dials Total", ""),
        ("vmagent_resident_memory_bytes", "RSS Memory", "bytes"),
    ]:
        rv, fv = rm.get(key), fm.get(key)
        lines.append(f"| {label} | {_fmt(rv, unit)} | {_fmt(fv, unit)} | {_pct_diff(rv, fv)} |")
    lines.append("")

    # --- Resource Usage ---
    lines.append("## Resource Usage (kubectl top)")
    lines.append("")
    lines.append("| Component | Real CPU | Fake CPU | Real Mem | Fake Mem |")
    lines.append("|-----------|----------|----------|----------|----------|")
    for key_cpu, key_mem, label in [
        ("vmagent_cpu", "vmagent_memory", "VMAgent"),
        ("konn_server_cpu", "konn_server_memory", "Konn Server"),
    ]:
        lines.append(f"| {label} | {rm.get(key_cpu, 'N/A')} | {fm.get(key_cpu, 'N/A')} "
                     f"| {rm.get(key_mem, 'N/A')} | {fm.get(key_mem, 'N/A')} |")
    lines.append("")

    # --- Konnectivity Server ---
    lines.append("## Konnectivity Server")
    lines.append("")
    lines.append("| Metric | Real | Fake | Δ% |")
    lines.append("|--------|------|------|----|")
    for key, label, unit in [
        ("konn_server_dial_mean_seconds", "Dial Mean", "s"),
        ("konn_server_dial_p50_seconds", "Dial P50", "s"),
        ("konn_server_dial_p90_seconds", "Dial P90", "s"),
        ("konn_server_dial_p99_seconds", "Dial P99", "s"),
        ("konn_server_dial_count", "Dial Count", ""),
        ("konn_server_dial_failure_count", "Dial Failures", ""),
        ("konn_server_goroutines", "Goroutines", ""),
        ("konn_server_grpc_connections", "gRPC Connections", ""),
        ("konn_server_ready_backend_connections", "Ready Backend Conns", ""),
        ("konn_server_established_connections", "Established Conns", ""),
        ("konn_server_http_connections", "HTTP Connections", ""),
        ("konn_server_pending_dials", "Pending Dials", ""),
        ("konn_server_stream_packets_total", "Stream Packets Total", ""),
        ("konn_server_stream_errors_total", "Stream Errors", ""),
        ("konn_server_frontend_write_mean_seconds", "Frontend Write Mean", "s"),
        ("konn_server_frontend_write_p50_seconds", "Frontend Write P50", "s"),
        ("konn_server_frontend_write_p90_seconds", "Frontend Write P90", "s"),
        ("konn_server_frontend_write_p99_seconds", "Frontend Write P99", "s"),
        ("konn_server_frontend_write_bytes_total", "Frontend Write Bytes", "bytes"),
        ("konn_server_frontend_read_bytes_total", "Frontend Read Bytes", "bytes"),
        ("konn_server_endpoint_dial_mean_seconds", "Endpoint Dial Mean", "s"),
        ("konn_server_endpoint_dial_p50_seconds", "Endpoint Dial P50", "s"),
        ("konn_server_endpoint_dial_p90_seconds", "Endpoint Dial P90", "s"),
        ("konn_server_endpoint_dial_p99_seconds", "Endpoint Dial P99", "s"),
        ("konn_server_resident_memory_bytes", "RSS Memory", "bytes"),
        ("konn_server_process_cpu_seconds_total", "CPU Seconds Total", "s"),
    ]:
        rv, fv = rm.get(key), fm.get(key)
        lines.append(f"| {label} | {_fmt(rv, unit)} | {_fmt(fv, unit)} | {_pct_diff(rv, fv)} |")
    lines.append("")

    # --- Konnectivity Agent ---
    lines.append("## Konnectivity Agent")
    lines.append("")
    lines.append("| Metric | Real | Fake | Δ% |")
    lines.append("|--------|------|------|----|")
    for key, label, unit in [
        ("konn_agent_goroutines", "Goroutines", ""),
        ("konn_agent_open_server_connections", "Open Server Conns", ""),
        ("konn_agent_open_endpoint_connections", "Open Endpoint Conns", ""),
        ("konn_agent_server_connection_failures", "Server Conn Failures", ""),
        ("konn_agent_endpoint_dial_failures", "Endpoint Dial Failures", ""),
        ("konn_agent_stream_packets_total", "Stream Packets Total", ""),
        ("konn_agent_stream_errors_total", "Stream Errors", ""),
        ("konn_agent_resident_memory_bytes", "RSS Memory", "bytes"),
        ("konn_agent_process_cpu_seconds_total", "CPU Seconds Total", "s"),
    ]:
        rv, fv = rm.get(key), fm.get(key)
        lines.append(f"| {label} | {_fmt(rv, unit)} | {_fmt(fv, unit)} | {_pct_diff(rv, fv)} |")
    lines.append("")

    # --- VMSingle Write Path ---
    lines.append("## VMSingle (Write Path)")
    lines.append("")
    lines.append("| Metric | Real | Fake | Δ% |")
    lines.append("|--------|------|------|----|")
    for key, label in [
        ("vmsingle_rows_inserted", "Rows Inserted"),
        ("vmsingle_http_requests_total", "HTTP Requests"),
        ("vmsingle_http_errors_total", "HTTP Errors"),
        ("vmsingle_series_created", "Series Created"),
        ("vmsingle_series_up_count", "Series Up Count"),
    ]:
        rv, fv = rm.get(key), fm.get(key)
        lines.append(f"| {label} | {_fmt(rv)} | {_fmt(fv)} | {_pct_diff(rv, fv)} |")
    lines.append("")

    # --- Pod Health ---
    lines.append("## Pod Health")
    lines.append("")
    lines.append("| Metric | Real | Fake |")
    lines.append("|--------|------|------|")
    for key, label in [
        ("pod_restarts_total", "Pod Restarts"),
        ("pod_oom_killed", "OOM Killed"),
        ("oom_events", "OOM Events"),
    ]:
        lines.append(f"| {label} | {rm.get(key, 'N/A')} | {fm.get(key, 'N/A')} |")
    lines.append("")

    # --- Pass/Fail ---
    lines.append("## Pass/Fail")
    lines.append("")
    rp = real.get("pass_criteria", {})
    fp = fake.get("pass_criteria", {})
    lines.append(f"- **Real**: {'PASS ✅' if real.get('pass') else 'FAIL ❌'}")
    lines.append(f"- **Fake**: {'PASS ✅' if fake.get('pass') else 'FAIL ❌'}")
    lines.append("")

    if rp or fp:
        lines.append("| Criterion | Real | Fake |")
        lines.append("|-----------|------|------|")
        all_keys = sorted(set(list(rp.keys()) + list(fp.keys())) - {"overall"})
        for k in all_keys:
            rv = rp.get(k)
            fv = fp.get(k)
            lines.append(f"| {k} | {'✅' if rv else '❌' if rv is not None else 'N/A'} "
                         f"| {'✅' if fv else '❌' if fv is not None else 'N/A'} |")
        lines.append("")

    # --- Summary ---
    lines.append("## Key Observations")
    lines.append("")
    observations = []

    # Check scrape success gap
    r_rate = rm.get("scrape_success_rate", 0)
    f_rate = fm.get("scrape_success_rate", 0)
    if abs(r_rate - f_rate) > 0.01:
        observations.append(f"- Scrape success rate differs: real={r_rate:.2%} vs fake={f_rate:.2%}")

    # Check memory gap
    r_mem = rm.get("vmagent_resident_memory_bytes", 0)
    f_mem = fm.get("vmagent_resident_memory_bytes", 0)
    if r_mem and f_mem:
        mem_ratio = f_mem / r_mem if r_mem else 0
        if mem_ratio > 1.5 or mem_ratio < 0.67:
            observations.append(f"- VMAgent memory: real={_fmt_bytes(r_mem)} vs fake={_fmt_bytes(f_mem)} "
                                f"(fake is {mem_ratio:.1f}x real)")

    # Check samples gap
    r_samples = rm.get("vmagent_samples_scraped", 0)
    f_samples = fm.get("vmagent_samples_scraped", 0)
    if r_samples and f_samples:
        sample_ratio = f_samples / r_samples if r_samples else 0
        observations.append(f"- Samples scraped: real={r_samples:.0f} vs fake={f_samples:.0f} "
                            f"(fake is {sample_ratio:.1f}x real)")

    # Check dial latency gap
    r_dial = rm.get("konn_server_dial_mean_seconds", 0)
    f_dial = fm.get("konn_server_dial_mean_seconds", 0)
    if r_dial and f_dial:
        observations.append(f"- Konn server dial mean: real={r_dial:.4f}s vs fake={f_dial:.4f}s")

    # Check series created
    r_series = rm.get("vmsingle_series_created", 0)
    f_series = fm.get("vmsingle_series_created", 0)
    if r_series and f_series:
        observations.append(f"- Series created: real={r_series:.0f} vs fake={f_series:.0f} "
                            f"({_pct_diff(r_series, f_series)})")

    # Check target count
    r_targets = rm.get("scrape_targets_total", 0)
    f_targets = fm.get("scrape_targets_total", 0)
    if r_targets != f_targets:
        observations.append(f"- Target count mismatch: real={r_targets} vs fake={f_targets}")

    if not observations:
        observations.append("- No significant differences observed at this tier.")

    lines.extend(observations)
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Compare real-node vs fake-exporter load test results")
    parser.add_argument("--real", required=True,
                        help="Path to real-targets result JSON")
    parser.add_argument("--fake", required=True,
                        help="Path to fake-exporter result JSON")
    parser.add_argument("--output", "-o", default="",
                        help="Output markdown file (default: stdout)")
    args = parser.parse_args()

    real_path = Path(args.real)
    fake_path = Path(args.fake)

    if not real_path.exists():
        print(f"Error: {real_path} not found", file=sys.stderr)
        sys.exit(1)
    if not fake_path.exists():
        print(f"Error: {fake_path} not found", file=sys.stderr)
        sys.exit(1)

    real = json.loads(real_path.read_text())
    fake = json.loads(fake_path.read_text())

    report = compare(real, fake)

    if args.output:
        out = Path(args.output)
        out.write_text(report)
        print(f"Report written to {out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
