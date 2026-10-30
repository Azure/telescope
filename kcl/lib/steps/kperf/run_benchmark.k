import azure_pipelines.ap.steps

# Runs a custom profile in pipeline; kperf owns output formatting and exit status.
RunKperfRunner = lambda profilePath: str, kubeconfig: str = "", resultPath: str = "" -> steps.Script {
    assert profilePath != "", "profilePath must not be empty"
    args = [
        '--config "${profilePath}"',
        '--kubeconfig "${kubeconfig}"' if kubeconfig else "",
        '--result "${resultPath}"' if resultPath else "",
    ]
    flags = " \\\n  ".join([arg for arg in args if arg])
    steps.Script {
        script = """
set -euo pipefail
set -x

kperf runner run \\
  ${flags}
"""
        displayName = "Run kperf runner"
    }
}

# RunKperfBenchmark runs runkperf bench with the given subcommand and flow control settings.
# Results are written to resultPath (default /tmp/tmp_results.json) for collection by CollectKperfResult.
RunKperfBenchmark = lambda benchmarkSubcmd: str, benchmarkSubcmdArgs: str, flowcontrol: str, kubeconfig: str, runnerImage: str, target: str = Undefined, resultPath: str = "/tmp/tmp_results.json" -> steps.Step {
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

# Tune initialDelaySeconds based on the known workload duration to minimise exposure
# to network disruption while fetching results over a port-forward connection.
FetchKperfRunnerGroupResult = lambda displayName: str = "Fetch kperf runner group result", resultPath: str = "", initialDelaySeconds: int = 0, timeoutInMinutes: int = 15 -> steps.Step {
    assert initialDelaySeconds >= 0, "initialDelaySeconds must be non-negative"
    steps.Bash {
        bash = """
set -euo pipefail
sleep ${initialDelaySeconds}
attempt=0
max_attempts=5
until kperf rg result --wait${' | tee "' + resultPath + '"' if resultPath else ""}; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$max_attempts" ]; then
    exit 1
  fi
  echo "attempt $attempt failed; retry in 10s" >&2
  sleep 10
done
"""
        displayName = displayName
        continueOnError = True
        timeoutInMinutes = timeoutInMinutes
    }
}

# RunKperfRunnerGroup runs `kperf rg run` with the specified runner image, runner
# group manifest, optional flow control setting, and optional affinity selector.
RunKperfRunnerGroup = lambda runnerImage: str, runnerGroup: str, flowcontrol: str = "", affinity: str = "", target: str = Undefined -> steps.Step {
    steps.Script {
        script = """
set -euo pipefail
set -x

run_rg() {
  args=(
    rg run
    --runner-image="${runnerImage}"
    --runnergroup="${runnerGroup}"
  )
  if [ -n "${flowcontrol}" ]; then
    args+=(--runner-flowcontrol="${flowcontrol}")
  fi
  if [ -n "${affinity}" ]; then
    args+=(--affinity="${affinity}")
  fi
  kperf "\${args[@]}"
}

cleanup_rg() {
  kperf rg delete || true
  kubectl -n runnergroups-kperf-io delete pod runnergroup-server \\
    --force --grace-period=0 --ignore-not-found=true --timeout=120s || true
}

cleanup_rg

attempt=0
max_attempts=10
until run_rg; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "kperf rg run failed after $attempt attempts" >&2
    kubectl -n runnergroups-kperf-io get pods -o wide || true
    kubectl -n runnergroups-kperf-io describe pod runnergroup-server || true
    kubectl -n runnergroups-kperf-io get events --sort-by=.lastTimestamp | tail -50 || true
    exit 1
  fi
  cleanup_rg
  echo "attempt $attempt failed; cleaning up and retrying in 120s" >&2
  sleep 120
done
"""
        displayName = "Run kperf runner group"
        target = target
    }
}
