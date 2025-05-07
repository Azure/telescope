import json
import argparse

from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def collect(results_dir, kbench_testnames, cloud_info, run_id, run_url, result_file):
    logger.info(f"Calling k-bench collect function with results_dir: {results_dir}, kbench_testnames: {kbench_testnames}, run_id: {run_id}, run_url: {run_url}, result_file: {result_file}, cloud_info: {cloud_info}")
    logger.info("Collecting k-bench results")
    test_result_data = {
        "results_dir": results_dir,
        "kbench_testnames": kbench_testnames,
        "result_file": result_file,
        "run_id": run_id
    }
    logger.info(f"Test result data to be written to result_file: {test_result_data}")
    with open(result_file, "w") as file:
        json.dump(test_result_data, file)
    logger.info(f"Successfully collected k-bench results and saved to {result_file}")


def main():
    parser = argparse.ArgumentParser(description="Collect k-bench test results.")

    parser.add_argument("results_dir", type=str, help="Path to the kbench results directory")
    parser.add_argument("kbench_testnames", type=str, help="Comma-separated list of kbench test names")
    parser.add_argument("cloud_info", type=str, help="Cloud information")
    parser.add_argument("run_id", type=str, help="Run ID")
    parser.add_argument("run_url", type=str, help="Run URL")
    parser.add_argument("result_file", type=str, help="Path to the result file")

    args = parser.parse_args()

    collect(args.results_dir, args.kbench_testnames, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == "__main__":
    main()
