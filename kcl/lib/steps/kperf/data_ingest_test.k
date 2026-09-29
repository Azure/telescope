test_batch_retry_cleanup = lambda {
    podStep = RunKperfDataIngest(
        dataType="pod",
        namespace="pod-data",
        name="test",
        totalGiB="1",
        size=10240)
    assert "kubectl delete pods --namespace pod-data --selector app=runkperf,podSetName=test-b$batch --wait=true" in podStep.script
    assert "runkperf data pod --namespace pod-data delete" not in podStep.script

    steps = [RunKperfDataIngest(
            dataType=dataType,
            namespace="data",
            name="test",
            total=1) for dataType in ["configmap", "event", "secret"]]
    assert "runkperf data configmap --namespace data delete test-b$batch --total $COUNT || true" in steps[0].script
    assert "runkperf data event --namespace data delete test-b$batch --total $COUNT || true" in steps[1].script
    assert "runkperf data secret --namespace data delete test-b$batch --total $COUNT || true" in steps[2].script
}
