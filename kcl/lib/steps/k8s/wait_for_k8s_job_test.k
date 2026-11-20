test_runs_as_bash_by_default = lambda {
    step = WaitForK8sJobFinished("ns", "job", continueOnError=True)
    assert step.displayName == "Wait for k8s job to finish: job"
    assert step.continueOnError
    assert 'kubectl -n "ns" get job "job"' in step.bash, step.bash
}

test_runs_in_azure_cli_with_service_connection = lambda {
    step = WaitForK8sJobFinished("ns", "job", continueOnError=True, serviceConnection="sc")
    assert step.task == "AzureCLI@2"
    assert step.inputs.azureSubscription == "sc"
    assert step.displayName == "Wait for k8s job to finish: job"
    assert step.continueOnError
    assert step.inputs.inlineScript == "set -exo pipefail\n" + WaitForK8sJobFinished("ns", "job").bash
}
