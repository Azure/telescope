import azure_pipelines.ap.steps
import lib.steps.azure

CreateWarpClient = lambda serviceConnection: str, manifest: str, workDir: str, resultDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Create the dedicated Warp client"
        ShellSetup(workDir, resultDir) + """
kubectl create --dry-run=server --validate=strict -f "${manifest}" > /dev/null
kubectl create -f "${manifest}" > /dev/null
kubectl wait -n alx-ns --for=condition=Ready pod/warp-client --timeout=600s
kubectl exec -n alx-ns warp-client -c warp \\
    -- /tools/warp --version > "${resultDir}/warp-version.txt"
"""
        stepName = "alluxio_warp_client"
    )
}

WarpGetSetup = lambda phase: "cold-start" | "warm-cache", workDir: str, resultDir: str, checksDir: str -> str {
    ShellSetup(workDir, resultDir) + AlluxioCommands(checksDir, resultDir) + """
phase="${phase}"
counts="$(cache_report "${"before-cold" if phase == "cold-start" else "before-warm"}")"
[[ "$(jq -r --arg field "${"uncached" if phase == "cold-start" else "all"}" '.[$field]' <<< "$counts")" == 16 ]] ||
    fail "$phase requires the expected cache state for all 16 objects"
hosts="$(kubectl get pods -n alx-ns -o json |
    jq -r '[.items[] | select(.metadata.name | test("^alluxio-worker-[0-9]+$"))
        | .status.podIP // empty | select(length > 0)
        | (if contains(":") then "[" + . + "]" else . end) + ":29998"] | join(",")')"
[[ -n "$hosts" ]] || fail "No Alluxio worker pod IPs found in alx-ns"
warp_get=(/tools/warp get "--host=$hosts" --bucket=blob --access-key=warp --secret-key=benchmark
    --region=us-east-1 --lookup=path --list-existing --noclear --full --json)
"""
}

RunColdWarpGet = lambda serviceConnection: str, workDir: str, resultDir: str, checksDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Run single-pass cold-start Warp GET"
        WarpGetSetup("cold-start", workDir, resultDir, checksDir) + """
command -v zstd >/dev/null || fail "zstd is required to read the raw Warp operations"
client_exec bash -eu -c '
    cd /results
    mkdir cold-start
    export TZ=UTC
    sync_start="$(date -d "+90 seconds" +%H:%M)"
    pids=()
    for key in object-{00..15}.bin; do
        # Warp GET samples with replacement, thus run an external loop.
        # Warp GET commands run in parallel.
        # Limit rps to once every 100s, so that it runs only once before duration timeout.
        "$@" --prefix="$key" --objects=1 --concurrent=1 --rps-limit=0.01 --duration=10s \\
            --syncstart="$sync_start" --benchdata="cold-start/$key" > "cold-start/$key.log" 2>&1 &
        pids+=("$!")
    done
    status=0
    for pid in "\${pids[@]}"; do wait "$pid" || status=1; done
    if (( status )); then cat cold-start/*.log >&2; exit 1; fi
    /tools/warp merge --benchdata=cold-start cold-start/object-{00..15}.bin.csv.zst
' _ "\${warp_get[@]}" > "${resultDir}/cold-start.log" 2>&1 ||
    fail "Cold Warp readers or merge failed; see cold-start.log"
client_exec cat /results/cold-start.csv.zst > "${resultDir}/cold-start.csv.zst"
zstd -dc "${resultDir}/cold-start.csv.zst" |
    jq -Rse -L "${checksDir}" 'include "checks"; cold_warp_summary' > "${resultDir}/cold-start-summary.json"
"""
        env = {BLOB_SAS = "$(BLOB_SAS)"}
    )
}

RunWarmWarpGet = lambda serviceConnection: str, workDir: str, resultDir: str, checksDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Run warm-cache Warp GET"
        WarpGetSetup("warm-cache", workDir, resultDir, checksDir) + """
start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
status=0
client_exec "\${warp_get[@]}" \\
    --concurrent=16 \\
    --duration=60s \\
    --obj.size=67108864 \\
    "--benchdata=/results/$phase" > "${resultDir}/$phase.log" 2>&1 || status=$?
end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
jq -n --arg phase "$phase" --arg command_start "$start" --arg command_end "$end" \\
    '$ARGS.named' > "${resultDir}/$phase-timing.json"
(( status == 0 )) || fail "Warp $phase command failed with status $status; see its log"
client_exec cat "/results/$phase.csv.zst" > "${resultDir}/$phase.csv.zst"
[[ -s "${resultDir}/$phase.csv.zst" ]] || fail "Warp raw data is empty for $phase"
client_exec /tools/warp analyze --full --json "/results/$phase.csv.zst" > "${resultDir}/$phase-analysis.json"
jq -e -L "${checksDir}" \\
    --slurpfile timing "${resultDir}/$phase-timing.json" \\
    'include "checks"; warp_summary + $timing[0] +
     {concurrency: 16, requested_duration_seconds: 60, dataset_bytes: 1073741824}' \\
    "${resultDir}/$phase-analysis.json" > "${resultDir}/$phase-summary.json"
counts="$(cache_report after-warm)"
[[ "$(jq -r '.all' <<< "$counts")" == 16 ]] || fail "Dataset was not fully cached after the warm phase"
"""
        env = {BLOB_SAS = "$(BLOB_SAS)"}
    )
}

PreloadAlluxioDataset = lambda serviceConnection: str, workDir: str, resultDir: str, checksDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Preload all 16 objects into the Alluxio cache"
        ShellSetup(workDir, resultDir) + AlluxioCommands(checksDir, resultDir) + """
alluxio job load --path /blob --submit | redact > "${resultDir}/preload-submit.txt"
deadline=$((SECONDS + 600))
while :; do
    alluxio job load --path /blob --progress | redact > "${resultDir}/preload.txt"
    state="$(sed -nE 's/^[[:space:]]*Job State:[[:space:]]*([A-Z_]+)[[:space:]]*$/\\1/p' "${resultDir}/preload.txt")"
    case "$state" in
        CREATED|RUNNING|SUCCEEDED) ;;
        *) fail "Preload failed or returned an unrecognized job state" ;;
    esac
    failed="$(sed -nE 's/^[[:space:]]*Files Failed:[[:space:]]*([0-9]+)[[:space:]]*$/\\1/p' "${resultDir}/preload.txt")"
    [[ "$failed" == 0 ]] || fail "Preload must report zero failed files"
    counts="$(cache_report before-warm)"
    if [[ "$state" == SUCCEEDED && "$(jq -r '.all' <<< "$counts")" == 16 ]]; then break; fi
    (( SECONDS < deadline )) || fail "All 16 files were not fully cached before timeout"
    sleep 10
done
"""
        stepName = "alluxio_preload"
        env = {BLOB_SAS = "$(BLOB_SAS)"}
    )
}
