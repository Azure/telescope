import azure_pipelines.ap.steps

# RunKperfBenchmark runs runkperf bench with the given subcommand and flow control settings.
# Results are written to resultPath (default /tmp/tmp_results.json) for collection by CollectKperfResult.
RunKperfBenchmark = lambda benchmarkSubcmd: str, benchmarkSubcmdArgs: str, flowcontrol: str, kubeconfig: str, runnerImage: str, target: str = None, resultPath: str = "/tmp/tmp_results.json" -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

export PATH="/:$PATH"

runkperf -v 3 bench \\
  --kubeconfig=${kubeconfig} \\
  --runner-image="${runnerImage}" \\
  --runner-flowcontrol="${flowcontrol}" \\
  --result ${resultPath} \\
  ${benchmarkSubcmd} ${benchmarkSubcmdArgs}
"""
        displayName = "Run kperf benchmark (${benchmarkSubcmd}, flowcontrol=${flowcontrol})"
        target = target
    }
}

# RunKperfRunnerGroup runs `kperf rg run` with the specified runner image, runner
# group manifest, optional flow control setting, and optional affinity selector.
RunKperfRunnerGroup = lambda runnerImage: str, runnerGroup: str, flowcontrol: str = "", affinity: str = "", target: str = None -> steps.Step {
    flowcontrolFlag = "--runner-flowcontrol=\"${flowcontrol}\" \\\n  " if flowcontrol else ""
    affinityFlag = "--affinity=\"${affinity}\" \\\n  " if affinity else ""
    steps.Script {
        script = """
set -euo pipefail
set -x

kperf rg delete

kperf rg run \\
  --runner-image=${runnerImage} \\
  --runnergroup="${runnerGroup}" \\
  ${flowcontrolFlag}${affinityFlag}
"""
        displayName = "Run kperf runner group"
        target = target
    }
}
