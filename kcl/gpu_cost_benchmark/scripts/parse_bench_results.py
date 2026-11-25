#!/usr/bin/env python3
import argparse
import json

RAW_SERIES_FIELDS = [
    "latencies",
    "queue_times",
    "ttfts",
    "itls",
    "tpots",
    "input_lens",
    "output_lens",
    "generated_texts",
]


def percentile(values, p):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return None
    k = (len(values) - 1) * p / 100.0
    lower = int(k)
    upper = min(lower + 1, len(values) - 1)
    if lower == upper:
        return values[lower]
    return values[lower] * (upper - k) + values[upper] * (k - lower)


def summarize_seconds(values):
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return None
    return {
        "count": len(values),
        "mean_ms": sum(values) / len(values) * 1000.0,
        "p50_ms": percentile(values, 50) * 1000.0,
        "p95_ms": percentile(values, 95) * 1000.0,
        "p99_ms": percentile(values, 99) * 1000.0,
    }


def compact_benchmark(benchmark):
    for field in ("latencies", "queue_times"):
        summary = summarize_seconds(benchmark.get(field, []))
        if summary is not None:
            benchmark[f"{field}_summary"] = summary
    for field in RAW_SERIES_FIELDS:
        benchmark.pop(field, None)
    return benchmark


def parse_cases(log_file, default_input_tokens, default_output_tokens):
    results = []
    current = None
    buf = []

    with open(log_file, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\\n")
            if line.startswith("__VLLM_CASE_JSON_BEGIN__"):
                parts = line.split()
                if len(parts) >= 6:
                    _, case_name, case_rps, case_input_tokens, case_output_tokens, case_num_prompts = parts[:6]
                else:
                    case_name = None
                    case_rps = None
                    case_input_tokens = None
                    case_output_tokens = None
                    case_num_prompts = None
                current = {
                    "case": case_name,
                    "request_rate": float(case_rps) if case_rps is not None else None,
                    "input_tokens_per_prompt": int(case_input_tokens) if case_input_tokens is not None else None,
                    "output_tokens_per_prompt": int(case_output_tokens) if case_output_tokens is not None else None,
                    "num_prompts": int(case_num_prompts) if case_num_prompts is not None else None,
                }
                buf = []
                continue
            if line == "__VLLM_CASE_JSON_END__":
                if current is None:
                    continue
                payload = "\\n".join(buf).strip()
                json_start = payload.find("{")
                json_end = payload.rfind("}")
                if json_start >= 0 and json_end > json_start:
                    payload_json = payload[json_start:json_end + 1]
                else:
                    payload_json = payload
                try:
                    benchmark = compact_benchmark(json.loads(payload_json))
                except json.JSONDecodeError as exc:
                    benchmark = {
                        "error": "benchmark_result_parse_failed",
                        "parse_error": str(exc),
                        "raw_payload_preview": payload[:500],
                        "completed": 0,
                        "failed": current["num_prompts"] or 0,
                        "request_rate": current["request_rate"],
                        "request_throughput": 0,
                        "p99_ttft_ms": None,
                        "duration": 0,
                    }
                current["vllm_benchmark"] = benchmark
                if current["request_rate"] is None:
                    benchmark_request_rate = benchmark.get("request_rate")
                    current["request_rate"] = float(benchmark_request_rate) if benchmark_request_rate is not None else None
                if current["num_prompts"] is None:
                    current["num_prompts"] = int(benchmark.get("num_prompts", 0) or 0)
                if current["input_tokens_per_prompt"] is None:
                    current["input_tokens_per_prompt"] = default_input_tokens
                if current["output_tokens_per_prompt"] is None:
                    current["output_tokens_per_prompt"] = default_output_tokens
                if current["case"] is None:
                    rps_suffix = int(current["request_rate"]) if current["request_rate"] is not None else "unknown"
                    current["case"] = f"in{current['input_tokens_per_prompt']}-out{current['output_tokens_per_prompt']}-rps{rps_suffix}"
                results.append(current)
                current = None
                buf = []
                continue
            if current is not None:
                buf.append(line)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--default-input-tokens", required=True, type=int)
    parser.add_argument("--default-output-tokens", required=True, type=int)
    args = parser.parse_args()

    results = parse_cases(args.log_file, args.default_input_tokens, args.default_output_tokens)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f)

    if not results:
        raise RuntimeError("No benchmark case JSON payloads were found in /tmp/vllm-bench.log")


if __name__ == "__main__":
    main()
