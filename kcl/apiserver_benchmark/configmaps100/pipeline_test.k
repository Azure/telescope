import lib.const

test_both_stages_install_authentication_tools = lambda {
    assert [stage.stage for stage in output.stages] == ["workload_low", "exempt"]
    assert output.resources == Undefined
    assert [stage.jobs[0].steps[1].task for stage in output.stages] == ["KubeloginInstaller@0", "KubeloginInstaller@0"]
    assert all stage in output.stages { stage.jobs[0].steps[1].inputs.kubeloginVersion == "latest" }
    assert all stage in output.stages { stage.jobs[0].steps[2].displayName == "Install runkperf binary" }
    assert all stage in output.stages { "docker pull ${RUNNER_IMAGE}" in stage.jobs[0].steps[2].script }
}

test_both_stages_create_entra_only_clusters = lambda {
    creates = [step for stage in output.stages for step in stage.jobs[0].steps if step.displayName == "Create cluster"]
    assert len(creates) == 2
    assert all step in creates { step.task == "AzureCLI@2" }
    assert all valid in [
        flag in step.inputs.inlineScript
        for step in creates
        for flag in ["--enable-managed-identity", "--enable-aad", "--enable-azure-rbac", "--disable-local-accounts"]
    ] { valid }
}

test_both_benchmarks_use_authenticated_host_tasks = lambda {
    benchmarks = [step for stage in output.stages for step in stage.jobs[0].steps if step.displayName.startswith("Run kperf benchmark")]
    assert len(benchmarks) == 2
    assert all step in benchmarks { step.task == "AzureCLI@2" }
    assert all step in benchmarks { step.target == Undefined }
    assert all step in benchmarks { step.inputs.azureSubscription == const.DEFAULT_SERVICE_CONNECTION }
    assert all valid in [
        command in step.inputs.inlineScript
        for step in benchmarks
        for command in [
            'export KUBECONFIG="$(Pipeline.Workspace)/kubeconfig"',
            "kubelogin convert-kubeconfig -l azurecli",
            'list_configmaps ${BENCHMARK_ARGS}',
            '--runner-image="${RUNNER_IMAGE}"',
            '--result "${RESULT_PATH}"',
        ]
    ] { valid }
    assert '--runner-flowcontrol="workload-low:1000"' in benchmarks[0].inputs.inlineScript
    assert '--runner-flowcontrol="exempt:5"' in benchmarks[1].inputs.inlineScript
}
