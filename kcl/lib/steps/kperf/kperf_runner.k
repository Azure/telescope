import azure_pipelines.ap.steps

# The caller installs kperf and owns the profile, kubeconfig, and result files.
RunKperfRunner = lambda profilePath: str, kubeconfig: str, resultPath: str, timeoutSeconds: int = 900 -> steps.Script {
    assert profilePath != "", "profilePath must not be empty"
    assert kubeconfig != "", "kubeconfig must not be empty"
    assert resultPath != "", "resultPath must not be empty"
    assert resultPath not in [profilePath, kubeconfig], "resultPath must not overwrite an input file"
    assert timeoutSeconds > 0, "timeoutSeconds must be positive"
    steps.Script {
        script = """
set -euo pipefail
if [ ! -r "${profilePath}" ] || [ ! -r "${kubeconfig}" ]; then
  echo "kperf requires a readable load profile and kubeconfig" >&2
  exit 1
fi
cat "${profilePath}"
rm -f -- "${resultPath}"
echo "Driver start: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
driver_status=0
timeout --signal=TERM --kill-after=30s ${timeoutSeconds}s \\
  kperf runner run \\
    --kubeconfig "${kubeconfig}" \\
    --config "${profilePath}" \\
    --result "${resultPath}" || driver_status=$?
echo "Driver end: $(date -u +%Y-%m-%dT%H:%M:%SZ); exit status: $driver_status"

report_status=0
if [ -s "${resultPath}" ]; then
  cat "${resultPath}"
  # Native total is configured total (zero for duration mode), not successes.
  jq -e '
    (.perSpecResults | type == "array" and length > 0)
    and (.aggregated | type == "object")
    and ([.perSpecResults[], .aggregated] | all(.[];
      (.total | type == "number" and . >= 0)
      and (.duration | type == "string" and length > 0)
      and (.percentileLatencies | type == "array" and length > 0)
      and (.errorStats // {} | type == "object" and all(.[]; type == "number" and . == 0))
    ))
  ' "${resultPath}" || report_status=$?
else
  echo "kperf did not produce a nonempty result file" >&2
  report_status=1
fi
if [ "$report_status" -ne 0 ]; then
  echo "kperf result is invalid or contains request failures" >&2
fi
if [ "$driver_status" -ne 0 ]; then exit "$driver_status"; fi
exit "$report_status"
"""
        displayName = "Run kperf runner"
    }
}
