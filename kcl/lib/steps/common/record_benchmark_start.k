import azure_pipelines.ap.steps

# RecordBenchmarkStart emits a step that captures the current UTC time as
# the BENCHMARK_START pipeline variable, for use downstream (e.g. as the
# start of a dashboard time range or metrics query window).
RecordBenchmarkStart = lambda -> steps.Step {
    steps.Bash {
        bash = """
set -exo pipefail
BENCHMARK_START=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
echo "Benchmark start time: $BENCHMARK_START"
echo "##vso[task.setvariable variable=BENCHMARK_START]$BENCHMARK_START"
"""
        displayName = "Record benchmark start time"
    }
}
