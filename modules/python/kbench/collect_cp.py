import json
import argparse

from utils.logger_config import get_logger, setup_logging
from kbench_parsers import cp_parser

setup_logging()
logger = get_logger(__name__)


def collect(results_dir, kbench_testnames, cloud_info, run_id, run_url, result_file):
    logger.info(f"""Calling k-bench collect function with
                results_dir: {results_dir},
                kbench_testnames: {kbench_testnames},
                run_id: {run_id},
                run_url: {run_url},
                result_file: {result_file},
                cloud_info: {cloud_info}""")
    result = {}
    result['run_id'] = run_id
    result['run_url'] = run_url
    result['cloud_info'] = cloud_info
    result['results'] = []

    test_results = []
    for testname in kbench_testnames.split(','):
        logger.info(f'Collecting k-bench results for test: {testname}')
        res = cp_parser.parse_test_results(results_dir, testname)
        if res:
            res['testname'] = testname
            test_results.append(res)
        else:
            logger.error(f'Failed to collect k-bench results for test: {testname}')
            continue

    if len(test_results) > 0:
        result['results'] = test_results
        logger.info(f'K-bench results data from {len(test_results)} test(s) will be written to result_file: {result_file}')
        with open(result_file, 'w') as file:
            json.dump(result, file)
        logger.info(f'Successfully collected k-bench results and saved to {result_file}')
    else:
        logger.error('No k-bench results to save!')
        raise Exception('No k-bench results to save!')

def main():
    parser = argparse.ArgumentParser(description='Collect k-bench test results.')

    parser.add_argument('results_dir', type=str, help='Path to the kbench results directory')
    parser.add_argument('kbench_testnames', type=str, help='Comma-separated list of kbench test names')
    parser.add_argument('cloud_info', type=str, help='Cloud information')
    parser.add_argument('run_id', type=str, help='Run ID')
    parser.add_argument('run_url', type=str, help='Run URL')
    parser.add_argument('result_file', type=str, help='Path to the result file')

    args = parser.parse_args()

    collect(args.results_dir, args.kbench_testnames, args.cloud_info, args.run_id, args.run_url, args.result_file)

if __name__ == '__main__':
    main()
