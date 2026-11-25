#!/usr/bin/env python3
import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--startup-metrics", required=True)
    args = parser.parse_args()

    with open(args.startup_metrics, encoding="utf-8") as f:
        metrics = json.load(f)

    value = metrics.get("t_model_load_to_gpu_seconds") or metrics.get("engine_init_seconds")
    if value is not None:
        print(value)


if __name__ == "__main__":
    main()
