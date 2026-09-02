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
  echo "attempt $attempt failed; retry in 120s" >&2
  sleep 120
  cleanup_rg
done
"""
        displayName = "Run kperf runner group"
        target = target
    }
}
