test_benchmark_uses_azure_login_and_explicit_kubeconfig = lambda {
    step = RunKperfBenchmark(
        "benchmark-service-connection",
        "list_configmaps",
        "--total 10000 --configmap-amount=100",
        "workload-low:1000",
        "/tmp/benchmark config",
        "ghcr.io/azure/kperf:0.3.4",
        "/tmp/benchmark results.json")
    assert step.task == "AzureCLI@2"
    assert step.target == Undefined
    assert step.displayName == "Run kperf benchmark (list_configmaps, flowcontrol=workload-low:1000)"
    assert step.inputs == {
        azureSubscription = "benchmark-service-connection"
        scriptType = "bash"
        scriptLocation = "inlineScript"
        inlineScript = """set -exo pipefail
set -euo pipefail

export KUBECONFIG="/tmp/benchmark config"
kubelogin convert-kubeconfig -l azurecli

runkperf -v 3 bench \\
  --kubeconfig="/tmp/benchmark config" \\
  --runner-image="ghcr.io/azure/kperf:0.3.4" \\
  --runner-flowcontrol="workload-low:1000" \\
  --result "/tmp/benchmark results.json" \\
  list_configmaps --total 10000 --configmap-amount=100
"""
    }
}

test_benchmark_default_result_path = lambda {
    step = RunKperfBenchmark(
        "benchmark-service-connection",
        "list_configmaps",
        "--total 10",
        "exempt:5",
        "/tmp/kubeconfig",
        "ghcr.io/azure/kperf:0.3.4")
    assert '--result "/tmp/tmp_results.json"' in step.inputs.inlineScript
    assert '--runner-flowcontrol="exempt:5"' in step.inputs.inlineScript
}
