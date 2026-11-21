import azure_pipelines.ap.steps
import json
import lib.steps.azure

# Steps that join the phases of the POSIX read pipeline (kcl/alluxio/posix_read) and summarize its results.

# Inserts shell lines into an AzCli step right after its setup lines, so they run under the step's error
# handling before anything else in it. AzCli puts AZ_CLI_SCRIPT_PREFIX in front of every script.
AZ_CLI_SCRIPT_PREFIX = "set -exo pipefail\n"
InsertAfterSetup = lambda step: any, setup: str, lines: str -> steps.Step {
    script = step.inputs.inlineScript
    head = AZ_CLI_SCRIPT_PREFIX + setup
    assert script.startswith(head), "step ${step.name} does not start with the given setup lines"
    step | {inputs = step.inputs | {inlineScript = head + lines + script[len(head):]}}
}

# Steps shared with the warp and S3 read pipelines print those pipelines' failure markers. PosixFailureMarker gives
# a step of this pipeline the POSIX marker instead, so that searching the run's log for ALLUXIO POSIX READ FAILED
# finds every failure; the shared steps, and the other pipelines' YAML, stay as they are.
PosixFailureMarker = lambda step: any -> steps.Step {
    mark = lambda script: str -> str {
        script.replace("ALLUXIO WARP FAILED", "ALLUXIO POSIX READ FAILED").replace("ALLUXIO S3 READ FAILED", "ALLUXIO POSIX READ FAILED")
    }
    step | {bash = mark(step.bash)} if typeof(step) == "Bash" else (step | {inputs = step.inputs | {inlineScript = mark(step.inputs.inlineScript)}} if typeof(step) == "Task" and step.inputs and "inlineScript" in step.inputs else step)
}

# RunPosixScenarios for one side and part, with what a part needs to run again by hand without leaving stale
# results. index.jsonl is shared by the sides and appended to, so the hot part first removes the side's lines of an
# earlier attempt: a second warm-up or hot entry of the side would fail the summary. The rest part keeps the hot
# lines and drops its own (RunPosixScenarios), and on BlobFuse2 and DACS it refuses a volume that no longer has the
# hot step's mount. A rest part that runs again still reads cold and concurrent sets that its earlier attempt read:
# a cache side then serves them from its cache, and BlobFuse2 can still hold them in its block cache. So BlobFuse2
# must be rerun from its hot part, which mounts the volume again, and a cache side from the creation of its cache
# pool. (The warm-up check itself passes on a cache that is already warm.)
# The Alluxio side also requires direct I/O for FUSE reads in both parts: its re-read scenario turns it off at the
# end, and a rerun after that would otherwise measure the hot, cold and concurrent reads through the page cache.
# Both the AlluxioCluster and the configuration every FUSE pod started with must have it on.
RunPosixSide = lambda serviceConnection: str, side: "bf2" | "dacs" | "alluxio", container: str, elbenchoImage: str, workDir: str, resultDir: str, checksDir: str, part: "hot" | "rest" -> steps.Step {
    directIoCheck = FUSE_DIRECT_IO_SHELL + """
direct_io="$(kubectl get alluxiocluster alluxio -n "$POSIX_NS" -o jsonpath='{.spec.properties.alluxio\\.fuse\\.enforce\\.direct\\.io\\.read}')"
[[ "$direct_io" == true ]] ||
    fail "alluxio.fuse.enforce.direct.io.read is '$direct_io', not true; set it and restart the FUSE pods before running this step"
require_fuse_direct_io true
""" if side == "alluxio" else ""
    removeSide = """if [[ -e "$POSIX_RESULT/index.jsonl" ]]; then
    jq -c --arg side ${side} 'select(.side != $side)' "$POSIX_RESULT/index.jsonl" > "$POSIX_WORK/index.jsonl"
    mv -- "$POSIX_WORK/index.jsonl" "$POSIX_RESULT/index.jsonl"
fi
""" if part == "hot" else ""
    checks = removeSide + directIoCheck
    InsertAfterSetup(RunPosixScenarios(serviceConnection, side, container, elbenchoImage, workDir, resultDir, checksDir, part), PosixShellSetup(workDir, resultDir), checks)
}

# PrepareWorkerNvme for the POSIX pipeline, which first refuses to go on if the DACS phase left anything on the
# Alluxio cache pool: a workerpool node that carries the DACS label, or a dacs-prereq pod on one. dacs-prereq builds
# RAID0 on the NVMe disks, which the page store needs. The guard lives here, not in the shared PrepareWorkerNvme,
# so the S3 read pipeline's step stays as it is.
PreparePosixWorkerNvme = lambda serviceConnection: str, manifest: str, workDir: str, resultDir: str, workerCount: int -> steps.Step {
    PosixFailureMarker(InsertAfterSetup(PrepareWorkerNvme(serviceConnection, manifest, workDir, resultDir, workerCount), S3ReadShellSetup(workDir, resultDir), """
worker_nodes="$(kubectl get nodes --selector agentpool=workerpool -o json)" || fail "could not list the workerpool nodes"
labelled="$(jq -r '[.items[] | select(.metadata.labels["dacs.azure.com/processing-unit"] != null) | .metadata.name] | join(" ")' <<< "$worker_nodes")" ||
    fail "could not read the labels of the workerpool nodes"
[[ -z "$labelled" ]] || fail "workerpool nodes carry the DACS label dacs.azure.com/processing-unit: $labelled"
prereq_pods="$(kubectl get pods -n kube-system -o json)" || fail "could not list the pods in kube-system"
prereq_on_workers="$(jq -r --argjson nodes "$(jq -c '[.items[].metadata.name]' <<< "$worker_nodes")" \\
    '[.items[] | select(.metadata.name | startswith("dacs-prereq")) | select(.spec.nodeName as $n | any($nodes[]; . == $n)) | .metadata.name] | join(" ")' \\
    <<< "$prereq_pods")" || fail "could not read the dacs-prereq pods"
[[ -z "$prereq_on_workers" ]] || fail "dacs-prereq pods run on workerpool nodes: $prereq_on_workers"
"""))
}

# CreateAlluxioCluster with the cache node count put into the POSIX_CACHE_COUNT placeholder of manifest
# (cluster.yaml), in a copy under workDir.
CreatePosixAlluxioCluster = lambda serviceConnection: str, alluxioImage: str, manifest: str, licenseManifest: str, workDir: str, resultDir: str -> steps.Step {
    InsertAfterSetup(CreateAlluxioCluster(serviceConnection, alluxioImage, "${workDir}/cluster.yaml", licenseManifest, workDir, resultDir), ShellSetup(workDir, resultDir), """
sed "s|POSIX_CACHE_COUNT|${POSIX_CACHE_COUNT}|" "${manifest}" > "${workDir}/cluster.yaml"
! grep -q POSIX_CACHE_COUNT "${workDir}/cluster.yaml" || fail "the POSIX_CACHE_COUNT placeholder is still in the cluster manifest"
""")
}

# Ends the DACS phase before its node pool is deleted: the elbencho pods, the Blob volume posix-data that
# reads through DACS and its read-only SAS Secret, then the Cache bench-cache. Waits until no DACS server pod
# is left, because the Alluxio phase reads the counters of 0 or exactly POSIX_CACHE_COUNT of them. The
# PrepareAlluxioFuseClients step that follows creates the elbencho pods again under the same names.
EndDacsPhase = lambda serviceConnection: str, workDir: str, resultDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Remove the DACS clients, volume and cache"
        PosixShellSetup(workDir, resultDir) + """
# 300 s bounds each deletion: a pod waits for its BlobFuse2 unmount, the Cache for its server pods.
kubectl delete pod -n "$POSIX_NS" -l ${POSIX_CLIENT_LABEL} --ignore-not-found --wait=true --timeout=300s
kubectl delete pvc posix-data -n "$POSIX_NS" --ignore-not-found --wait=true --timeout=300s
kubectl delete pv posix-data --ignore-not-found --wait=true --timeout=300s
kubectl delete secret posix-sas -n "$POSIX_NS" --ignore-not-found
kubectl delete caches.storage.azure.com bench-cache -n ${DACS_NAMESPACE} --ignore-not-found --wait=true --timeout=300s
deadline=$((SECONDS + 300))
while :; do
    pods="$(kubectl get pods -n ${DACS_NAMESPACE} -o name)" || fail "could not list the pods in ${DACS_NAMESPACE}"
    left="$(grep '^pod/bench-cache-' <<< "$pods" || true)"
    [[ -n "$left" ]] || break
    (( SECONDS < deadline )) || fail "DACS server pods still exist 300 s after the Cache was deleted: $left"
    sleep 10
done
"""
        stepName = "posix_end_dacs"
    )
}

# Writes summary.json from the results of the three sides:
#   scenarios   scenario_summary of the hot and cold runs (runs-<side>.jsonl), with the Blob bytes of each cold rep
#   concurrent  concurrent_summary of the concurrent reads, which carries the hot and warm-up Blob bytes
#               (hot_egress_summary) and the Blob bytes of every indexed group
#   reread      reread_summary of each side of the re-read scenario
#   versions    BlobFuse2 on a client node, the Blob CSI driver, the DACS extension, CLI extensions and controller,
#               Alluxio and elbencho (also versions.json); a version that could not be read is null and fails
#               the step after summary.json is written
# Blob bytes come from the storage account's Azure Monitor Egress metric, attributed to the indexed groups of
# each side (blob_egress_by_rep). Every index line counts except the single hot runs, which the one hot entry
# of the side spans. egress.json and versions.json stay in the results even when a later check fails, because the
# storage account is deleted with the resource group. This is an AzCli step because it queries Azure.
SummarizePosixRead = lambda serviceConnection: str, subscription: str, resourceGroup: str, cluster: str, account: str, workDir: str, resultDir: str, checksDir: str -> steps.Step {
    reread = [scenario for scenario in POSIX_SCENARIOS if scenario.group == "reread"]
    assert len(reread) == 1, "the summary expects exactly one re-read scenario"
    # The hot and cold scenarios with their sides, which scenario_summary must cover exactly. A string
    # interpolation cannot hold this expression's braces.
    measured = json.encode([{"scenario": measuredScenario.id, "sides": sorted(measuredScenario.sides)} for measuredScenario in POSIX_SCENARIOS if measuredScenario.group in ["hot", "cold"]])
    # Every side of the benchmark, sorted; the index and the measured runs must hold exactly these.
    sides = json.encode(sorted({side: True for scenario in POSIX_SCENARIOS for side in scenario.sides}))
    # One re-read summary per side: the two reads of the scenario, and on Alluxio the worker counter snapshots
    # taken before, between and after them.
    rereadOf = lambda side: str -> str {
        counterArgs = "".join(["    --rawfile ${snapshot} \"$POSIX_RESULT/counters-${side}-${reread[0].id}-${snapshot}.prom\" \\\n" for snapshot in ["before", "between", "after"]]) if side == "alluxio" else ""
        counterField = " + {counters: {before: $before, between: $between, after: $after}}" if side == "alluxio" else ""
        """jq -n -L "${checksDir}" -L "${checksDir}/.." \\
    --slurpfile runs "$POSIX_RESULT/runs-${side}.jsonl" \\
    --slurpfile concurrent "$POSIX_WORK/concurrent.json" \\
${counterArgs}    'include "checks";
    def reread_result($rep):
        [$runs[] | select(.scenario == "${reread[0].id}" and .rep == $rep)]
        | if length == 1 then .[0].result else failed("expected one ${side} re-read \\($rep), found \\(length)") end;
    {side: "${side}", first: reread_result(1), second: reread_result(2), blob_bytes_by_rep: $concurrent[0].blob_bytes_by_rep}${counterField}
    | {side} + reread_summary' \\
    >> "$POSIX_WORK/reread.jsonl" || fail "could not summarize the ${side} re-reads"
"""
    }
    azure.AzCli(
        serviceConnection
        "Summarize the POSIX read results"
        PosixShellSetup(workDir, resultDir) + """
jq -c 'select(.group != "hot" or .rep == "all")' "$POSIX_RESULT/index.jsonl" > "$POSIX_WORK/egress-index.jsonl"
jq -se -L "${checksDir}" -L "${checksDir}/.." --argjson sides '${sides}' 'include "checks"; require_sides($sides)' \\
    "$POSIX_WORK/egress-index.jsonl" > /dev/null || fail "the index does not hold the runs of every side"
first_start="$(jq -sr 'map(.start) | min' "$POSIX_WORK/egress-index.jsonl")"
last_end="$(jq -sr 'map(.end) | max' "$POSIX_WORK/egress-index.jsonl")"
resource_id="$(az storage account show \\
    --name "${account}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --query id \\
    --output tsv)"
[[ -n "$resource_id" ]] || fail "could not resolve the resource ID of ${account}"
# The last group of a side owns the minute after its last end plus 3 trailing minutes (attribute_egress), and
# Azure Monitor publishes a minute about one minute late: the first query waits until 6 minutes after the last
# end. Later queries follow every 60 s, for up to 10 more minutes, until every window has data and the bounds
# of concurrent_summary hold. egress.json ends up as the output of the last query.
ready_at=$(( $(date -u -d "$last_end" +%s) + 360 ))
now="$(date -u +%s)"
(( now >= ready_at )) || sleep $((ready_at - now))
deadline=$((SECONDS + 600))
while :; do
    # A failed query (a transient Azure Monitor error) is retried like an incomplete one. Every successful query
    # replaces egress.json in the results, so the metric survives the resource group even if a later check fails.
    if az monitor metrics list \\
        --resource "$resource_id" \\
        --metric Egress \\
        --interval PT1M \\
        --aggregation Total \\
        --start-time "$first_start" \\
        --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$POSIX_WORK/egress.json" 2> "$POSIX_WORK/egress.err"; then
        cp -- "$POSIX_WORK/egress.json" "$POSIX_RESULT/egress.json"
        # Each client of a concurrent rep reads the whole set <side>-cc-r<rep> of its side; hot_bytes is the size
        # of the hot data set.
        if jq -n -L "${checksDir}" -L "${checksDir}/.." \\
            --slurpfile index "$POSIX_WORK/egress-index.jsonl" \\
            --slurpfile metrics "$POSIX_RESULT/egress.json" \\
            --slurpfile counters "$POSIX_RESULT/counters-alluxio.jsonl" \\
            --argjson reps ${POSIX_REPS} \\
            --argjson clients ${POSIX_CLIENT_COUNT} \\
            --argjson client_bytes ${POSIX_CC_FILES * POSIX_BIG_FILE_GIB * 1073741824} \\
            --argjson hot_bytes ${POSIX_HOT_FILES * POSIX_HOT_FILE_MIB * 1048576} \\
            'include "checks"; {index: $index, metrics: $metrics[0], counters: $counters, hot_bytes: $hot_bytes} | concurrent_summary($reps; $clients; $client_bytes)' \\
            > "$POSIX_WORK/concurrent.json" 2> "$POSIX_WORK/concurrent.err"; then
            break
        fi
        status="$(tail -n 1 "$POSIX_WORK/concurrent.err")"
    else
        status="the Egress query failed: $(tail -n 1 "$POSIX_WORK/egress.err")"
    fi
    if (( SECONDS >= deadline )); then
        cat "$POSIX_WORK/concurrent.err" "$POSIX_WORK/egress.err" >&2 2> /dev/null || true
        fail "could not attribute Blob egress within 16 minutes of the last run ($status); see egress.json"
    fi
    echo "Blob egress is not complete yet: $status"
    sleep 60
done

jq -c 'select(.group == "hot" or .group == "cold")' "$POSIX_RESULT"/runs-*.jsonl > "$POSIX_WORK/summary-runs.jsonl"
jq -n -L "${checksDir}" -L "${checksDir}/.." \\
    --slurpfile runs "$POSIX_WORK/summary-runs.jsonl" \\
    --slurpfile concurrent "$POSIX_WORK/concurrent.json" \\
    --argjson reps ${POSIX_REPS} \\
    --argjson sides '${sides}' \\
    'include "checks"; {runs: ($runs | require_sides($sides)), blob_bytes_by_rep: $concurrent[0].blob_bytes_by_rep} | scenario_summary($reps)' \\
    > "$POSIX_WORK/scenarios.json" || fail "could not summarize the hot and cold scenarios"
# Every hot and cold scenario must be present with exactly the sides that run it.
jq -e --argjson expected '${measured}' \\
    '(map({scenario, sides: (.sides | keys)}) | sort_by(.scenario)) == ($expected | sort_by(.scenario))' \\
    "$POSIX_WORK/scenarios.json" > /dev/null || fail "the summary does not cover exactly the hot and cold scenarios of every side"

: > "$POSIX_WORK/reread.jsonl"
""" + "".join([rereadOf(side) for side in reread[0].sides]) + """# Versions of what ran, read after the egress evidence is saved. Each probe that fails leaves its version null
# in versions.json and summary.json, which are written either way; then the step fails.
# BlobFuse2 is installed on the node by the Blob CSI driver, so a pod on a client node runs the node's own binary.
clients="$(kubectl get pods -n "$POSIX_NS" -l ${POSIX_CLIENT_LABEL} -o json)" || clients='{"items": []}'
client_pod="$(jq -r '.items | sort_by(.metadata.name) | .[0].metadata.name // empty' <<< "$clients")" || true
client_node="$(jq -r '.items | sort_by(.metadata.name) | .[0].spec.nodeName // empty' <<< "$clients")" || true
elbencho_version="$(kubectl exec -n "$POSIX_NS" "$client_pod" -- elbencho --version | awk '$1 == "*" && $2 == "Version:" { print $3 }')" || true
blobfuse2_version=""
if [[ -n "$client_node" ]]; then
    kubectl delete pod blobfuse2-version -n "$POSIX_NS" --ignore-not-found > /dev/null || true
    kubectl create -n "$POSIX_NS" -f - > /dev/null << MANIFEST || true
apiVersion: v1
kind: Pod
metadata:
  name: blobfuse2-version
spec:
  nodeName: $client_node
  restartPolicy: Never
  tolerations:
    - operator: Exists
  containers:
    - name: version
      image: ${POSIX_DROP_CACHE_IMAGE}
      command: [chroot, /host, /usr/bin/blobfuse2, --version]
      volumeMounts:
        - {name: host, mountPath: /host, readOnly: true}
  volumes:
    - name: host
      hostPath: {path: /}
MANIFEST
    # 180 s covers pulling the image on the node and running one command.
    if kubectl wait -n "$POSIX_NS" --for=jsonpath='{.status.phase}'=Succeeded pod/blobfuse2-version --timeout=180s > /dev/null; then
        blobfuse2_version="$(kubectl logs -n "$POSIX_NS" blobfuse2-version | awk '$1 == "blobfuse2" && $2 == "version" { print $3 }')" || true
    fi
    kubectl delete pod blobfuse2-version -n "$POSIX_NS" --ignore-not-found > /dev/null || true
fi
blob_csi_image="$(kubectl get daemonset csi-blob-node -n kube-system -o json |
    jq -r '.spec.template.spec.containers[] | select(.name == "blob") | .image')" || true
dacs_controller_image="$(kubectl get deployment dacs-manager -n kube-system -o json |
    jq -r '[.spec.template.spec.containers[].image] | join(" ")')" || true
# The DACS extension's own version, from the cluster's extension list in Azure Resource Manager, so this step
# does not need the CLI extensions, which only EnableDacs installs, for its own step.
cluster_id="$(az aks show \\
    --name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --query id \\
    --output tsv)" || true
dacs_extension="$(az rest \\
    --method get \\
    --url "https://management.azure.com$cluster_id/providers/Microsoft.KubernetesConfiguration/extensions?api-version=2023-05-01" |
    jq -r '.value[] | select(.name == "distributedaccelerator") | .properties.currentVersion // .properties.version // empty')" || true
alluxio_image="$(kubectl get alluxiocluster alluxio -n "$POSIX_NS" -o json | jq -r '.spec.image + ":" + .spec.imageTag')" || true
jq -n \\
    --arg blobfuse2 "$blobfuse2_version" \\
    --arg blob_csi_image "$blob_csi_image" \\
    --arg dacs_extension "$dacs_extension" \\
    --arg dacs_aks_preview "${DACS_AKS_PREVIEW_VERSION}" \\
    --arg dacs_k8s_extension "${DACS_K8S_EXTENSION_VERSION}" \\
    --arg dacs_controller_image "$dacs_controller_image" \\
    --arg alluxio_image "$alluxio_image" \\
    --arg elbencho "$elbencho_version" \\
    '$ARGS.named | map_values(if . == "" then null else . end)' > "$POSIX_RESULT/versions.json"

jq -n \\
    --slurpfile scenarios "$POSIX_WORK/scenarios.json" \\
    --slurpfile concurrent "$POSIX_WORK/concurrent.json" \\
    --slurpfile reread "$POSIX_WORK/reread.jsonl" \\
    --slurpfile versions "$POSIX_RESULT/versions.json" \\
    '{scenarios: $scenarios[0], concurrent: $concurrent[0], reread: $reread, versions: $versions[0]}' \\
    > "$POSIX_RESULT/summary.json"
missing="$(jq -r '[to_entries[] | select(.value == null) | .key] | join(", ")' "$POSIX_RESULT/versions.json")"
[[ -z "$missing" ]] || fail "could not read the version of $missing; see versions.json"
"""
        stepName = "posix_summary"
        timeoutInMinutes = POSIX_STEP_TIMEOUT_MINUTES
    )
}
