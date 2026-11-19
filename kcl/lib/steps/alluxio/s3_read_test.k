import runtime

test_s3_read_scenarios = lambda {
    assert S3_READ_SCENARIOS == [
        S3ReadScenario {id = 1, name = "remote small get", kind = "get", dataset = "remote", objects = "small", concurrency = 16}
        S3ReadScenario {id = 2, name = "remote big get", kind = "get", dataset = "remote", objects = "big", concurrency = 16}
        S3ReadScenario {id = 3, name = "range 256 KiB", kind = "range", dataset = "local", objects = "big", concurrency = 16, rangeBytes = 262144}
        S3ReadScenario {id = 4, name = "range 1 MiB", kind = "range", dataset = "local", objects = "big", concurrency = 16, rangeBytes = 1048576}
        S3ReadScenario {id = 5, name = "local small get", kind = "get", dataset = "local", objects = "small", concurrency = 16}
        S3ReadScenario {id = 6, name = "range 4 MiB", kind = "range", dataset = "local", objects = "big", concurrency = 16, rangeBytes = 4194304}
        S3ReadScenario {id = 7, name = "range 16 MiB", kind = "range", dataset = "local", objects = "big", concurrency = 16, rangeBytes = 16777216}
        S3ReadScenario {id = 8, name = "big get concurrency 1", kind = "get", dataset = "local", objects = "big", concurrency = 1}
        S3ReadScenario {id = 9, name = "big get concurrency 4", kind = "get", dataset = "local", objects = "big", concurrency = 4}
        S3ReadScenario {id = 10, name = "big get concurrency 16", kind = "get", dataset = "local", objects = "big", concurrency = 16}
    ]
}

test_s3_read_scenario_groups = lambda {
    # Every scenario runs exactly once, in S3_READ_SCENARIOS order.
    assert [id for group in S3_READ_SCENARIO_GROUPS for id in group] == [scenario.id for scenario in S3_READ_SCENARIOS]
    steps = [RunS3ReadScenarios("sc", "local", "remote", "w", "r", "c", group) for group in S3_READ_SCENARIO_GROUPS]
    assert [step.name for step in steps] == ["s3_read_scenarios_1_3", "s3_read_scenarios_4_5", "s3_read_scenarios_6_7", "s3_read_scenarios_8_10"]
    # Only the first group starts the index and warms the datasets.
    assert [": > \"r/runs/index.jsonl\"" in step.inputs.inlineScript for step in steps] == [True, False, False, False]
    assert ["\nwarm_dataset local /blob\n" in step.inputs.inlineScript for step in steps] == [True, False, False, False]
}

test_s3_read_scenarios_rejects_unknown_ids = lambda {
    failure = runtime.catch(lambda {
        RunS3ReadScenarios("sc", "local", "remote", "w", "r", "c", [3, 2])
    })
    assert "ids must be scenario ids" in failure, failure
}

test_summary_and_sas_check_need_no_azure_login = lambda {
    # Neither step uses az or kubectl, so neither depends on the service connection signing in;
    # the SAS check must run before results are published even when that sign-in fails.
    assert SummarizeS3Read("w", "r", "c").bash
    assert RefuseSasInResults("w", "r").bash
}

test_range_requires_size = lambda {
    failure = runtime.catch(lambda {
        S3ReadScenario {
            id = 1
            name = "range without size"
            kind = "range"
            dataset = "local"
            objects = "big"
            concurrency = 16
            rangeBytes = 0
        }
    })
    assert failure != ""
}

test_get_rejects_range_size = lambda {
    failure = runtime.catch(lambda {
        S3ReadScenario {
            id = 1
            name = "get with size"
            kind = "get"
            dataset = "local"
            objects = "big"
            concurrency = 16
            rangeBytes = 1024
        }
    })
    assert failure != ""
}

test_scenario_steps_check_the_cache_hit = lambda {
    # Every scenario group reads the workers' UFS counter around each Alluxio rep and fails a rep that read
    # from Blob; the helper is defined once per step.
    scripts = [RunS3ReadScenarios("sc", "local", "remote", "w", "r", "c", group).inputs.inlineScript for group in S3_READ_SCENARIO_GROUPS]
    assert all script in scripts {
        len(script.split("\nworker_ufs_bytes() {")) == 2 and "served_from_cache($ufs_bytes)" in script
    }
}

test_checkpoint_load_spreads_pods_over_workers = lambda {
    script = RunCheckpointLoad("sc", "sub", "rg", "local", "w", "r", "c").inputs.inlineScript
    assert len(script.split("\nworker_ufs_bytes() {")) == 2
    assert "HOST_OFFSET=$((index - 1))" in script
}
