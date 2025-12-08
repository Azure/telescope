#!/bin/bash
#
# Analyze ClusterLoader2 results
#

set -e

if [ -z "$ROOT_DIR" ]; then
    echo "Error: ROOT_DIR is not set. Please run the setup cell first."
    exit 1
fi

export PYTHONPATH="${ROOT_DIR}/modules/python:${PYTHONPATH}"
RESULTS_DIR="${ROOT_DIR}/scenarios/perf-eval/image-pull-test/results"

python3 -m clusterloader2.image_pull.analyze_results "$RESULTS_DIR" "$@"

exit $?
