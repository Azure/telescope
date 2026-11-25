#!/usr/bin/env python3
import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--startup-metrics", required=True)
    parser.add_argument("--benchmark-results", required=True)
    parser.add_argument("--duration-seconds", required=True, type=int)
    parser.add_argument("--gpu-ready-seconds", required=True, type=int)
    parser.add_argument("--vllm-ready-seconds", required=True, type=int)
    parser.add_argument("--model-load-seconds", default="")
    parser.add_argument("--gpu-node-count", required=True, type=int)
    parser.add_argument("--hourly-cost", required=True, type=float)
    parser.add_argument("--location", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--gpu-vm-size", required=True)
    parser.add_argument("--target-duration-seconds", required=True, type=int)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--pipeline-name", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.startup_metrics, "r", encoding="utf-8") as f:
        startup_metrics = json.load(f)

    with open(args.benchmark_results, "r", encoding="utf-8") as f:
        benchmark_cases = json.load(f)

    model_load_seconds_raw = args.model_load_seconds.strip()
    model_load_seconds = float(model_load_seconds_raw) if model_load_seconds_raw else None

    total_cost = args.gpu_node_count * args.hourly_cost * args.duration_seconds / 3600.0
    total_tokens = 0
    for case in benchmark_cases:
        benchmark = case["vllm_benchmark"]
        case_tokens = int(benchmark.get("total_input_tokens", 0)) + int(benchmark.get("total_output_tokens", 0))
        case["total_tokens"] = case_tokens
        case["traffic_cost_usd"] = args.gpu_node_count * args.hourly_cost * float(benchmark.get("duration", 0)) / 3600.0
        case["traffic_cost_per_1m_tokens_usd"] = case["traffic_cost_usd"] * 1_000_000 / case_tokens if case_tokens else None
        target_rps = float(case["request_rate"]) if case.get("request_rate") is not None else 0.0
        throughput = float(benchmark.get("request_throughput", 0) or 0)
        case["throughput_to_target_ratio"] = throughput / target_rps if target_rps else None
        total_tokens += case_tokens

    baseline_p99_ttft = float(benchmark_cases[0]["vllm_benchmark"].get("p99_ttft_ms", 0) or 0) if benchmark_cases else 0
    saturation_case = None
    for case in benchmark_cases:
        benchmark = case["vllm_benchmark"]
        failed = int(benchmark.get("failed", 0) or 0)
        p99_ttft = float(benchmark.get("p99_ttft_ms", 0) or 0)
        throughput_ratio = case.get("throughput_to_target_ratio")
        reasons = []
        if failed > 0:
            reasons.append("failed_requests")
        if throughput_ratio is not None and throughput_ratio < 0.95:
            reasons.append("throughput_below_95pct_of_target")
        if baseline_p99_ttft and p99_ttft > max(100.0, 2.0 * baseline_p99_ttft):
            reasons.append("p99_ttft_gt_2x_baseline_or_100ms")
        if reasons:
            saturation_case = {
                "case": case["case"],
                "request_rate": case.get("request_rate"),
                "reasons": reasons,
                "request_throughput": benchmark.get("request_throughput"),
                "throughput_to_target_ratio": throughput_ratio,
                "p99_ttft_ms": p99_ttft,
                "baseline_p99_ttft_ms": baseline_p99_ttft,
                "failed_requests": failed,
            }
            break

    saturation_detection = {
        "detected": saturation_case is not None,
        "first_saturation_case": saturation_case,
        "criteria": [
            "failed_requests > 0",
            "request_throughput / request_rate < 0.95",
            "p99_ttft_ms > max(100ms, 2x baseline p99 TTFT)",
        ],
    }

    result = {
        "scenario": "vllm-qwen25-7b-cost-efficiency-rps-sweep",
        "region": args.location,
        "cluster": args.cluster,
        "model": args.model,
        "runtime": "vllm",
        "gpu_vm_size": args.gpu_vm_size,
        "gpu_node_count": args.gpu_node_count,
        "request_rates": [1, 2, 3, 5, 10, 15],
        "benchmark_case_specs": [
            "30:512:128",
            "35:512:128",
            "40:512:128",
            "5:1024:512",
            "10:1024:512",
            "15:1024:512",
            "1:2048:2048",
            "2:2048:2048",
            "3:2048:2048",
            "5:2048:2048",
        ],
        "target_duration_seconds_per_case": args.target_duration_seconds,
        "duration_seconds": args.duration_seconds,
        "gpu_ready_seconds": args.gpu_ready_seconds,
        "vllm_ready_seconds": args.vllm_ready_seconds,
        "model_load_seconds": model_load_seconds,
        "startup_seconds": args.gpu_ready_seconds + args.vllm_ready_seconds,
        **startup_metrics,
        "estimated_cost_usd": total_cost,
        "estimated_cost_per_1m_tokens_usd": total_cost * 1_000_000 / total_tokens if total_tokens else None,
        "saturation_detection": saturation_detection,
        "benchmark_cases": benchmark_cases,
    }

    wrapped_result = {
        "timestamp": args.timestamp,
        "run_id": args.run_id,
        "run_url": args.run_url,
        "pipeline": args.pipeline_name,
        "result": result,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(wrapped_result, f)


if __name__ == "__main__":
    main()
