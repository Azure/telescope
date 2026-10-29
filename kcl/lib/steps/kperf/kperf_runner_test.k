test_runner_paths_and_default_timeout = lambda {
    step = RunKperfRunner("/tmp/load profile.yaml", "/tmp/kubeconfig", "/tmp/result.json")
    assert step.displayName == "Run kperf runner"
    assert '--config "/tmp/load profile.yaml"' in step.script
    assert '--kubeconfig "/tmp/kubeconfig"' in step.script
    assert '--result "/tmp/result.json"' in step.script
    assert "timeout --signal=TERM --kill-after=30s 900s" in step.script
}

test_runner_custom_timeout = lambda {
    step = RunKperfRunner("/tmp/profile.yaml", "/tmp/kubeconfig", "/tmp/result.json", timeoutSeconds=1200)
    assert "timeout --signal=TERM --kill-after=30s 1200s" in step.script
    assert "900s" not in step.script
}
