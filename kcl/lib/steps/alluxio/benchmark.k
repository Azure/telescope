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

RunColdGet = lambda workDir: str, resultDir: str, checksDir: str -> steps.Bash {
    steps.Bash {
        name = "alluxio_cold"
        displayName = "Run one cold pass over all 16 objects"
        bash = ShellSetup(workDir, resultDir) + AlluxioCommands(checksDir, resultDir) + """
counts="$(cache_report before-cold)"
[[ "$(jq -r '.uncached' <<< "$counts")" == 16 ]] ||
    fail "Cold-start requires all 16 objects to be uncached"
host="$(kubectl get pod alluxio-worker-0 -n alx-ns -o json |
    jq -er '.status.podIP'):29998"
start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
status=0
kubectl exec -n alx-ns warp-client -c warp -- env HOST="$host" sh -c '
    set -u
    start_ns="$(date +%s%N)"
    pids=""
    for index in $(seq 0 15); do
        key="$(printf "object-%02d.bin" "$index")"
        (
            AWS_ACCESS_KEY_ID=warp \\
            AWS_SECRET_ACCESS_KEY=benchmark \\
            AWS_EC2_METADATA_DISABLED=true \\
            AWS_MAX_ATTEMPTS=1 \\
            AWS_PAGER= \\
            aws --endpoint-url "http://$HOST" --region us-east-1 --no-cli-pager \\
                s3api get-object --bucket blob --key "$key" /dev/null \\
                > "/results/cold-start-$key.json" \\
                2> "/results/cold-start-$key.err"
        ) &
        pids="$pids $!"
    done
    command_status=0
    for process_id in $pids; do
        wait "$process_id" || command_status=1
    done
    end_ns="$(date +%s%N)"
    printf "{\\"start_unix_ns\\":%s,\\"end_unix_ns\\":%s,\\"request_count\\":16}\\n" \\
        "$start_ns" "$end_ns" > /results/cold-start-client-timing.json
    exit "$command_status"
' > "${resultDir}/cold-start.log" 2>&1 || status=$?
end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
jq -n --arg phase cold-start --arg command_start "$start" --arg command_end "$end" \\
    '$ARGS.named' > "${resultDir}/cold-start-timing.json"
kubectl exec -n alx-ns warp-client -c warp -- sh -c 'cat /results/cold-start-*.err' \\
    >> "${resultDir}/cold-start.log" || true
(( status == 0 )) || fail "Cold-start S3 GETs failed with status $status; see its log"
kubectl exec -n alx-ns warp-client -c warp -- cat /results/cold-start-client-timing.json \\
    > "${workDir}/cold-start-client-timing.json"
kubectl exec -n alx-ns warp-client -c warp -- sh -c 'cat /results/cold-start-object-*.json' \\
    > "${workDir}/cold-start-responses.json"
jq -e -n -L "${checksDir}" \\
    --slurpfile timing "${workDir}/cold-start-client-timing.json" \\
    --slurpfile responses "${workDir}/cold-start-responses.json" \\
    --slurpfile command_timing "${resultDir}/cold-start-timing.json" \\
    'include "checks"; cold_summary($timing; $responses) + $command_timing[0]' \\
    > "${resultDir}/cold-start-summary.json"
counts="$(cache_report after-cold)"
[[ "$(jq -r '.all' <<< "$counts")" == 16 ]] || fail "Cold-start did not cache all 16 objects"
"""
        env = {
            BLOB_SAS = "$(BLOB_SAS)"
        }
    }
}

RunWarmGet = lambda workDir: str, resultDir: str, checksDir: str -> steps.Bash {
    steps.Bash {
        name = "alluxio_warm"
        displayName = "Run warm-cache Warp GET"
        bash = ShellSetup(workDir, resultDir) + AlluxioCommands(checksDir, resultDir) + """
phase=warm-cache
counts="$(cache_report before-warm)"
[[ "$(jq -r '.all' <<< "$counts")" == 16 ]] ||
    fail "Warm-cache requires all 16 objects to be cached"
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
counts="$(cache_report after-warm)"
[[ "$(jq -r '.all' <<< "$counts")" == 16 ]] || fail "Dataset was not fully cached after the warm phase"
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
