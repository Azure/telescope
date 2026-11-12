import azure_pipelines.ap.steps

CreateWarpClient = lambda manifest: str, workDir: str, resultDir: str -> steps.Bash {
    steps.Bash {
        name = "alluxio_warp_client"
        displayName = "Create the dedicated Warp client"
        bash = ShellSetup(workDir, resultDir) + """
kubectl create --dry-run=server --validate=strict -f "${manifest}" > /dev/null
kubectl create -f "${manifest}" > /dev/null
kubectl wait -n alx-ns --for=condition=Ready pod/warp-client --timeout=600s
kubectl exec -n alx-ns warp-client -c warp \\
    -- /tools/warp --version > "${resultDir}/warp-version.txt"
"""
    }
}

RunWarpGet = lambda phase: "cold-start" | "warm-cache", workDir: str, resultDir: str, checksDir: str -> steps.Bash {
    steps.Bash {
        displayName = "Run ${phase} Warp GET"
        bash = ShellSetup(workDir, resultDir) + AlluxioCommands(checksDir, resultDir) + """
phase="${phase}"
counts="$(cache_report "${"before-cold" if phase == "cold-start" else "before-warm"}")"
[[ "$(jq -r --arg field "${"uncached" if phase == "cold-start" else "all"}" '.[$field]' <<< "$counts")" == 16 ]] ||
    fail "$phase requires the expected cache state for all 16 objects"
host="$(kubectl get pod alluxio-worker-0 -n alx-ns -o json |
    jq -er '.status.podIP'):29998"
start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
status=0
client_exec /tools/warp get \\
    "--host=$host" \\
    --bucket=blob \\
    --access-key=warp \\
    --secret-key=benchmark \\
    --region=us-east-1 \\
    --lookup=path \\
    --list-existing \\
    --noclear \\
    --concurrent=16 \\
    --duration=60s \\
    --obj.size=67108864 \\
    --full \\
    --json \\
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
if [[ "$phase" == warm-cache ]]; then
    counts="$(cache_report after-warm)"
    [[ "$(jq -r '.all' <<< "$counts")" == 16 ]] || fail "Dataset was not fully cached after the warm phase"
fi
"""
        env = {
            BLOB_SAS = "$(BLOB_SAS)"
        }
    }
}

PreloadAlluxioDataset = lambda workDir: str, resultDir: str, checksDir: str -> steps.Bash {
    steps.Bash {
        name = "alluxio_preload"
        displayName = "Preload all 16 objects into the Alluxio cache"
        bash = ShellSetup(workDir, resultDir) + AlluxioCommands(checksDir, resultDir) + """
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
        env = {
            BLOB_SAS = "$(BLOB_SAS)"
        }
    }
}
