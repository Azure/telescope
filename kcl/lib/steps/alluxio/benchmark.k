import azure_pipelines.ap.steps

CacheCommands = lambda checksDir: str -> str {
    REDACT_OUTPUT + """
alluxio() {
    kubectl exec -n alx-ns alluxio-coordinator-0 \\
        -c alluxio-coordinator -- alluxio "$@"
}
client_exec() {
    kubectl exec -n alx-ns warp-client -c warp -- "$@"
}
cache_report() {
    alluxio fs check-cached --path /blob --recursive --limit 17 |
        redact > "$result_dir/cache-$1.txt"
    jq -Rse -L "${checksDir}" 'include "checks"; cache_counts' "$result_dir/cache-$1.txt"
}
"""
}

CreateWarpClient = lambda workDir: str, resultDir: str -> steps.Bash {
    steps.Bash {
        name = "alluxio_warp_client"
        displayName = "Create the dedicated Warp client"
        bash = ShellSetup(workDir, resultDir) + """
cat > "$work_dir/client.yaml" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: warp-client
  namespace: alx-ns
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  nodeSelector: {agentpool: clientpool}
  tolerations:
    - {key: warp, operator: Equal, value: "true", effect: NoSchedule}
  volumes:
    - {name: tools, emptyDir: {}}
    - {name: results, emptyDir: {}}
  initContainers:
    - name: install-warp
      image: curlimages/curl:8.12.1
      securityContext: {runAsUser: 0}
      command:
        - sh
        - -c
        - |
          set -eu
          curl --fail --silent --show-error --location \\
            https://github.com/minio/warp/releases/download/v${WARP_VERSION}/warp_Linux_x86_64.tar.gz \\
            -o /tools/warp.tar.gz
          cd /tools
          echo '${WARP_SHA256}  warp.tar.gz' | sha256sum -c -
          tar -xzf warp.tar.gz warp
          chmod +x warp
      volumeMounts:
        - {name: tools, mountPath: /tools}
  containers:
    - name: warp
      image: debian:12.9-slim
      command: [sh, -c, "sleep 10800"]
      resources:
        requests: {cpu: "4", memory: 8Gi}
        limits: {cpu: "6", memory: 12Gi}
      volumeMounts:
        - {name: tools, mountPath: /tools}
        - {name: results, mountPath: /results}
EOF
kubectl create --dry-run=server --validate=strict -f "$work_dir/client.yaml" > /dev/null
kubectl create -f "$work_dir/client.yaml" > /dev/null
kubectl wait -n alx-ns --for=condition=Ready pod/warp-client --timeout=600s
kubectl exec -n alx-ns warp-client -c warp \\
    -- /tools/warp --version > "$result_dir/warp-version.txt"
"""
    }
}

RunWarpGet = lambda phase: "cold-start" | "warm-cache", workDir: str, resultDir: str, checksDir: str -> steps.Bash {
    steps.Bash {
        name = "alluxio_cold" if phase == "cold-start" else "alluxio_warm"
        displayName = "Run ${phase} Warp GET"
        bash = ShellSetup(workDir, resultDir) + CacheCommands(checksDir) + """
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
    "--benchdata=/results/$phase" > "$result_dir/$phase.log" 2>&1 || status=$?
end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
jq -n --arg phase "$phase" --arg command_start "$start" --arg command_end "$end" \\
    '$ARGS.named' > "$result_dir/$phase-timing.json"
(( status == 0 )) || fail "Warp $phase command failed with status $status; see its log"
client_exec cat "/results/$phase.csv.zst" > "$result_dir/$phase.csv.zst"
[[ -s "$result_dir/$phase.csv.zst" ]] || fail "Warp raw data is empty for $phase"
client_exec /tools/warp analyze --full --json "/results/$phase.csv.zst" > "$result_dir/$phase-analysis.json"
jq -e -L "${checksDir}" \\
    --slurpfile timing "$result_dir/$phase-timing.json" \\
    --arg warp_version "${WARP_VERSION}" --arg alluxio_version "${ALLUXIO_TAG}" \\
    'include "checks"; warp_summary + $timing[0] + $ARGS.named +
     {concurrency: 16, requested_duration_seconds: 60, dataset_bytes: 1073741824}' \\
    "$result_dir/$phase-analysis.json" > "$work_dir/summary.json"
mv -- "$work_dir/summary.json" "$result_dir/$phase-summary.json"
if [[ "$phase" == warm-cache ]]; then
    counts="$(cache_report after-warm)"
    [[ "$(jq -r '.all' <<< "$counts")" == 16 ]] || fail "Dataset was not fully cached after the warm phase"
fi
"""
    }
}

PreloadAlluxioDataset = lambda workDir: str, resultDir: str, checksDir: str -> steps.Bash {
    steps.Bash {
        name = "alluxio_preload"
        displayName = "Preload all 16 objects into the Alluxio cache"
        bash = ShellSetup(workDir, resultDir) + CacheCommands(checksDir) + """
alluxio job load --path /blob --submit | redact > "$result_dir/preload-submit.txt"
deadline=$((SECONDS + 600))
while :; do
    alluxio job load --path /blob --progress | redact > "$result_dir/preload.txt"
    state="$(sed -nE 's/^[[:space:]]*Job State:[[:space:]]*([A-Z_]+)[[:space:]]*$/\\1/p' "$result_dir/preload.txt")"
    case "$state" in
        CREATED|RUNNING|SUCCEEDED) ;;
        *) fail "Preload failed or returned an unrecognized job state" ;;
    esac
    failed="$(sed -nE 's/^[[:space:]]*Files Failed:[[:space:]]*([0-9]+)[[:space:]]*$/\\1/p' "$result_dir/preload.txt")"
    [[ "$failed" == 0 ]] || fail "Preload must report zero failed files"
    counts="$(cache_report before-warm)"
    if [[ "$state" == SUCCEEDED && "$(jq -r '.all' <<< "$counts")" == 16 ]]; then break; fi
    (( SECONDS < deadline )) || fail "All 16 files were not fully cached before timeout"
    sleep 10
done
"""
    }
}
