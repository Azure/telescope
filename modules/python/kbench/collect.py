#import json
#import os
import argparse
#import math

#from datetime import datetime, timezone
#from clients.kubernetes_client import KubernetesClient, client as k8s_client
from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)

def collect(results_dir, cloud_info, run_id, run_url, result_file):
    logger.info(f"Calling k-bench collect function with results_dir: {results_dir}, cloud_info: {cloud_info}, run_id: {run_id}, run_url: {run_url}, result_file: {result_file}")
    logger.info("Collecting k-bench results")

def main():
    parser = argparse.ArgumentParser(description="Collect k-bench test results.")

    parser.add_argument("results_dir", type=str, help="Path to the kbench results directory")
    parser.add_argument("cloud_info", type=str, help="Cloud information")
    parser.add_argument("run_id", type=str, help="Run ID")
    parser.add_argument("run_url", type=str, help="Run URL")
    parser.add_argument("result_file", type=str, help="Path to the result file")

    args = parser.parse_args()

    collect(args.results_dir, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()
