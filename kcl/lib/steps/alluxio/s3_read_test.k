import runtime

test_s3_read_object_sets = lambda {
    assert S3_READ_BIG_OBJECTS == S3ReadObjects {keyFormat = "object-%02d.bin", count = 16, bytes = 67108864}
    assert S3_READ_SMALL_OBJECTS == S3ReadObjects {keyFormat = "small/obj-%04d.bin", count = 1024, bytes = 1048576}
}

test_s3_read_scenario_groups = lambda {
    big = S3_READ_BIG_OBJECTS
    small = S3_READ_SMALL_OBJECTS
    assert S3_READ_SCENARIO_GROUPS == [
        [
            S3ReadScenario {id = 1, name = "remote small get", kind = "get", dataset = "remote", objects = small, concurrency = 16}
            S3ReadScenario {id = 2, name = "remote big get", kind = "get", dataset = "remote", objects = big, concurrency = 16}
            S3ReadScenario {id = 3, name = "range 256 KiB", kind = "range", dataset = "local", objects = big, concurrency = 16, rangeBytes = 262144}
        ]
        [
            S3ReadScenario {id = 4, name = "range 1 MiB", kind = "range", dataset = "local", objects = big, concurrency = 16, rangeBytes = 1048576}
            S3ReadScenario {id = 5, name = "local small get", kind = "get", dataset = "local", objects = small, concurrency = 16}
        ]
        [
            S3ReadScenario {id = 6, name = "range 4 MiB", kind = "range", dataset = "local", objects = big, concurrency = 16, rangeBytes = 4194304}
            S3ReadScenario {id = 7, name = "range 16 MiB", kind = "range", dataset = "local", objects = big, concurrency = 16, rangeBytes = 16777216}
        ]
        [
            S3ReadScenario {id = 8, name = "big get concurrency 1", kind = "get", dataset = "local", objects = big, concurrency = 1}
            S3ReadScenario {id = 9, name = "big get concurrency 4", kind = "get", dataset = "local", objects = big, concurrency = 4}
            S3ReadScenario {id = 10, name = "big get concurrency 16", kind = "get", dataset = "local", objects = big, concurrency = 16}
        ]
    ]
    # summary.json requires exactly scenarios 1-10, each run once.
    assert [scenario.id for group in S3_READ_SCENARIO_GROUPS for scenario in group] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    steps = [RunS3ReadScenarios("sc", "local", "remote", "w", "r", "c", group) for group in S3_READ_SCENARIO_GROUPS]
    assert [step.name for step in steps] == ["s3_read_scenarios_1_3", "s3_read_scenarios_4_5", "s3_read_scenarios_6_7", "s3_read_scenarios_8_10"]
    # Only the first group starts the index and warms the datasets.
    assert [": > \"r/runs/index.jsonl\"" in step.inputs.inlineScript for step in steps] == [True, False, False, False]
    assert ["\nwarm_dataset local /blob\n" in step.inputs.inlineScript for step in steps] == [True, False, False, False]
}

test_derived_scenario_fields = lambda {
    scenarios = [scenario for group in S3_READ_SCENARIO_GROUPS for scenario in group]
    assert [scenario.requestBytes for scenario in scenarios] == [1048576, 67108864, 262144, 1048576, 1048576, 4194304, 16777216, 67108864, 67108864, 67108864]
    assert [scenario.batchRequests for scenario in scenarios] == [50, 4, 50, 50, 50, 50, 16, 4, 4, 4]
    assert [scenario.maxRequestsPerWorker for scenario in scenarios] == [100000, 2000, 100000, 100000, 100000, 100000, 100000, 2000, 2000, 2000]
}

test_derived_scenario_fields_cannot_be_set = lambda {
    failures = [runtime.catch(lambda {
        S3ReadScenario {id = 1, name = "n", kind = "get", dataset = "local", objects = S3_READ_BIG_OBJECTS, concurrency = 1, requestBytes = 1}
    }), runtime.catch(lambda {
        S3ReadScenario {id = 1, name = "n", kind = "get", dataset = "local", objects = S3_READ_BIG_OBJECTS, concurrency = 1, batchRequests = 50}
    }), runtime.catch(lambda {
        S3ReadScenario {id = 1, name = "n", kind = "get", dataset = "local", objects = S3_READ_BIG_OBJECTS, concurrency = 1, maxRequestsPerWorker = 100000}
    })]
    assert ["requestBytes is derived" in failures[0], "batchRequests is derived" in failures[1], "maxRequestsPerWorker is derived" in failures[2]] == [True, True, True], "${failures}"
}

test_scenario_calls = lambda {
    calls = [line for group in S3_READ_SCENARIO_GROUPS for line in RunS3ReadScenarios("sc", "loc", "rem", "w", "r", "c", group).inputs.inlineScript.split("\n") if line.startswith("run_scenario ")]
    assert calls == [
        """run_scenario '{"id": 1, "name": "remote small get", "kind": "get", "dataset": "remote", "concurrency": 16, "rangeBytes": 0}' xregion rem remote-data KIND=get KEY_FORMAT='small/obj-%04d.bin' KEY_COUNT=1024 OBJECT_BYTES=1048576 CONCURRENCY=16 RANGE_BYTES=0 BATCH_REQUESTS=50 MAX_REQUESTS_PER_WORKER=100000"""
        """run_scenario '{"id": 2, "name": "remote big get", "kind": "get", "dataset": "remote", "concurrency": 16, "rangeBytes": 0}' xregion rem remote-data KIND=get KEY_FORMAT='object-%02d.bin' KEY_COUNT=16 OBJECT_BYTES=67108864 CONCURRENCY=16 RANGE_BYTES=0 BATCH_REQUESTS=4 MAX_REQUESTS_PER_WORKER=2000"""
        """run_scenario '{"id": 3, "name": "range 256 KiB", "kind": "range", "dataset": "local", "concurrency": 16, "rangeBytes": 262144}' blob loc local-data KIND=range KEY_FORMAT='object-%02d.bin' KEY_COUNT=16 OBJECT_BYTES=67108864 CONCURRENCY=16 RANGE_BYTES=262144 BATCH_REQUESTS=50 MAX_REQUESTS_PER_WORKER=100000"""
        """run_scenario '{"id": 4, "name": "range 1 MiB", "kind": "range", "dataset": "local", "concurrency": 16, "rangeBytes": 1048576}' blob loc local-data KIND=range KEY_FORMAT='object-%02d.bin' KEY_COUNT=16 OBJECT_BYTES=67108864 CONCURRENCY=16 RANGE_BYTES=1048576 BATCH_REQUESTS=50 MAX_REQUESTS_PER_WORKER=100000"""
        """run_scenario '{"id": 5, "name": "local small get", "kind": "get", "dataset": "local", "concurrency": 16, "rangeBytes": 0}' blob loc local-data KIND=get KEY_FORMAT='small/obj-%04d.bin' KEY_COUNT=1024 OBJECT_BYTES=1048576 CONCURRENCY=16 RANGE_BYTES=0 BATCH_REQUESTS=50 MAX_REQUESTS_PER_WORKER=100000"""
        """run_scenario '{"id": 6, "name": "range 4 MiB", "kind": "range", "dataset": "local", "concurrency": 16, "rangeBytes": 4194304}' blob loc local-data KIND=range KEY_FORMAT='object-%02d.bin' KEY_COUNT=16 OBJECT_BYTES=67108864 CONCURRENCY=16 RANGE_BYTES=4194304 BATCH_REQUESTS=50 MAX_REQUESTS_PER_WORKER=100000"""
        """run_scenario '{"id": 7, "name": "range 16 MiB", "kind": "range", "dataset": "local", "concurrency": 16, "rangeBytes": 16777216}' blob loc local-data KIND=range KEY_FORMAT='object-%02d.bin' KEY_COUNT=16 OBJECT_BYTES=67108864 CONCURRENCY=16 RANGE_BYTES=16777216 BATCH_REQUESTS=16 MAX_REQUESTS_PER_WORKER=100000"""
        """run_scenario '{"id": 8, "name": "big get concurrency 1", "kind": "get", "dataset": "local", "concurrency": 1, "rangeBytes": 0}' blob loc local-data KIND=get KEY_FORMAT='object-%02d.bin' KEY_COUNT=16 OBJECT_BYTES=67108864 CONCURRENCY=1 RANGE_BYTES=0 BATCH_REQUESTS=4 MAX_REQUESTS_PER_WORKER=2000"""
        """run_scenario '{"id": 9, "name": "big get concurrency 4", "kind": "get", "dataset": "local", "concurrency": 4, "rangeBytes": 0}' blob loc local-data KIND=get KEY_FORMAT='object-%02d.bin' KEY_COUNT=16 OBJECT_BYTES=67108864 CONCURRENCY=4 RANGE_BYTES=0 BATCH_REQUESTS=4 MAX_REQUESTS_PER_WORKER=2000"""
        """run_scenario '{"id": 10, "name": "big get concurrency 16", "kind": "get", "dataset": "local", "concurrency": 16, "rangeBytes": 0}' blob loc local-data KIND=get KEY_FORMAT='object-%02d.bin' KEY_COUNT=16 OBJECT_BYTES=67108864 CONCURRENCY=16 RANGE_BYTES=0 BATCH_REQUESTS=4 MAX_REQUESTS_PER_WORKER=2000"""
    ], "${calls}"
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
            objects = S3_READ_BIG_OBJECTS
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
            objects = S3_READ_BIG_OBJECTS
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
    # Each rep reads one checkpoint set: 8 keys set-<set>/part-0..7.bin of 2 GiB.
    assert 'KEY_FORMAT="set-$set/part-%d.bin" KEY_COUNT=8\n        OBJECT_BYTES=2147483648' in script
}
