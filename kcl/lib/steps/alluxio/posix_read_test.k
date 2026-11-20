import runtime

test_posix_scenarios = lambda {
    assert POSIX_SCENARIOS == [
        PosixScenario {id = "13-16a", group = "hot", blockSize = "4K", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "13-16b", group = "hot", blockSize = "64K", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "17", group = "hot", blockSize = "1M", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "18-t8", group = "hot", blockSize = "4M", threads = 8, bf2BlockMiB = 4, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "18-t32", group = "hot", blockSize = "4M", threads = 32, bf2BlockMiB = 4, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "19-t1", group = "hot", blockSize = "64K", threads = 1, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "19-t4", group = "hot", blockSize = "64K", threads = 4, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "20-t16", group = "hot", blockSize = "64K", threads = 16, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "20-t64", group = "hot", blockSize = "64K", threads = 64, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "21-22", group = "cold", blockSize = "64K", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "23-24", group = "concurrent", blockSize = "16M", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
        PosixScenario {id = "29", group = "reread", blockSize = "16M", threads = 1, bf2BlockMiB = 0, sides = ["bf2", "alluxio"]}
    ]
}

test_reread_requires_default_mount = lambda {
    failure = runtime.catch(lambda {
        PosixScenario {
            id = "29"
            group = "reread"
            blockSize = "16M"
            threads = 1
            bf2BlockMiB = 1
            sides = ["bf2", "alluxio"]
        }
    })
    assert failure != ""
}

test_non_reread_requires_block_size = lambda {
    failure = runtime.catch(lambda {
        PosixScenario {
            id = "17"
            group = "hot"
            blockSize = "1M"
            threads = 8
            bf2BlockMiB = 0
            sides = ["bf2", "dacs", "alluxio"]
        }
    })
    assert failure != ""
}

test_threads_must_be_positive = lambda {
    failure = runtime.catch(lambda {
        PosixScenario {
            id = "17"
            group = "hot"
            blockSize = "1M"
            threads = 0
            bf2BlockMiB = 1
            sides = ["bf2", "dacs", "alluxio"]
        }
    })
    assert failure != ""
}

test_scale = lambda {
    assert PosixScaled("smoke", 5, 2) == 2
    assert PosixScaled("full", 5, 2) == 5
    failure = runtime.catch(lambda {
        PosixScaled("huge", 5, 2)
    })
    assert failure != ""
    # Generation without -D scale yields the full size.
    assert POSIX_CACHE_COUNT == 5
    assert POSIX_CLIENT_COUNT == 5
    assert POSIX_SYSTEM_COUNT == 3
    assert POSIX_HOT_FILES == 480
    assert POSIX_HOT_FILE_MIB == 512
    assert POSIX_COLD_FILES == 25
    assert POSIX_CC_FILES == 8
    assert POSIX_BIG_FILE_GIB == 2
    assert POSIX_REREAD_GIB == 8
    assert POSIX_REP_SECONDS == 60
    assert POSIX_REPS == 3
}

test_mount_options = lambda {
    bf2 = lambda blockMiB: int -> [str] {
        ["--read-only=true", "--allow-other=true", "--disable-kernel-cache=true", "--block-cache", "--block-cache-block-size=${blockMiB}", "--block-cache-prefetch=128", "--block-cache-parallelism=128"]
    }
    assert PosixMountOptions("bf2", 1) == bf2(1)
    assert PosixMountOptions("bf2", 4) == bf2(4)
    assert PosixMountOptions("bf2", 0) == ["--read-only=true", "--allow-other=true"]
    assert PosixMountOptions("dacs", 1) == ["--read-only=true", "--allow-other=true", "--disable-kernel-cache=true", "--block-cache=false", "--streaming=false", "--preload=false", "--distributed-cache-discovery-endpoint=bench-cache-discovery.dacs-cache-system.svc.cluster.local:9065", "--distributed-cache-block-size=1", "--distributed-cache-prefetch=128", "--distributed-cache-parallelism=128"]
}

test_dacs_mount_uses_1_mib_blocks = lambda {
    assert runtime.catch(lambda {
        PosixMountOptions("dacs", 4)
    }) != ""
}

test_run_limits = lambda {
    assert PosixReadLimit(16 * 1073741824) == 463
    assert PosixReadLimit(0) == POSIX_RUN_SLACK_SECONDS
    # Every long step stops before the one-hour Entra ID sign-in can lapse.
    assert POSIX_STEP_TIMEOUT_MINUTES < 60
    assert all part in POSIX_SIDE_PARTS {
        RunPosixScenarios("c", "bf2", "posix-data", "e", "w", "r", "d", part).timeoutInMinutes == POSIX_STEP_TIMEOUT_MINUTES
    }
    assert GeneratePosixDatasets("c", "s", "g", "l", "a", "posix-data", "e", "w", "r", "d").timeoutInMinutes == POSIX_STEP_TIMEOUT_MINUTES
}

test_failure_marker = lambda {
    marked = PosixFailureMarker(RefuseSasInResults("w", "r"))
    assert "ALLUXIO S3 READ FAILED" not in marked.bash
    assert "ALLUXIO POSIX READ FAILED: a SAS signature" in marked.bash
    nvme = PreparePosixWorkerNvme("c", "m", "w", "r", 5).inputs.inlineScript
    assert "ALLUXIO S3 READ FAILED" not in nvme and "ALLUXIO WARP FAILED" not in nvme
}
