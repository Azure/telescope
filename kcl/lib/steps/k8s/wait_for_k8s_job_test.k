test_default_display_name = lambda {
    step = WaitForK8sJobFinished("benchmark", "ingest")
    explicit = WaitForK8sJobFinished("benchmark", "ingest", displayName=Undefined)
    assert step.displayName == "Wait for k8s job to finish: ingest"
    assert explicit.displayName == step.displayName
    assert explicit.inputs == step.inputs
}

test_custom_display_name_preserves_wait_behavior = lambda {
    defaultStep = WaitForK8sJobFinished("benchmark", "verify", timeoutSeconds=9000, continueOnError=True, serviceConnection="sc")
    customStep = WaitForK8sJobFinished("benchmark", "verify", "Verify data after migration", timeoutSeconds=9000, continueOnError=True, serviceConnection="sc")
    assert customStep.displayName == "Verify data after migration"
    assert customStep.inputs == defaultStep.inputs
    assert customStep.continueOnError == defaultStep.continueOnError
}

test_empty_display_name_is_not_undefined = lambda {
    step = WaitForK8sJobFinished("benchmark", "verify", displayName="")
    assert step.displayName == ""
}
