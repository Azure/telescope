import azure_pipelines.ap.steps
import json
import lib.steps.azure

# The workerpool and the clientpool have this many nodes, with one Alluxio worker and one client pod
# on each. kcl/alluxio/s3_read/cluster.yaml must set worker.count to S3_READ_WORKER_COUNT.
S3_READ_WORKER_COUNT = 5
S3_READ_CLIENT_COUNT = 5

# ShellSetup plus this pipeline's failure marker for fail() and the ERR trap. Steps shared with the
# warp pipeline (install, mount, diagnostics) keep ShellSetup's own marker.
S3ReadShellSetup = lambda workDir: str, resultDir: str -> str {
    ShellSetup(workDir, resultDir) + """
fail() {
    echo "ALLUXIO S3 READ FAILED: $*" >&2
    exit 1
}
trap 'echo "ALLUXIO S3 READ FAILED: command at line $LINENO exited with status $?" >&2' ERR
"""
}

schema S3ReadScenario:
    id: int
    name: str
    kind: "get" | "range"
    dataset: "local" | "remote"
    objects: "big" | "small"
    concurrency: int
    rangeBytes: int = 0

    check:
        1 <= id <= 10
        concurrency > 0
        (rangeBytes > 0) == (kind == "range"), "rangeBytes must be set exactly for range scenarios"

# Scenarios 11 and 12 are not in this table; they are executed separately
# because they are measured through Azure Monitor egress rather than client timing.
S3_READ_SCENARIOS: [S3ReadScenario] = [
    S3ReadScenario {id = 1, name = "remote small get", kind = "get", dataset = "remote", objects = "small", concurrency = 16}
    S3ReadScenario {id = 2, name = "remote big get", kind = "get", dataset = "remote", objects = "big", concurrency = 16}
    S3ReadScenario {id = 3, name = "range 256 KiB", kind = "range", dataset = "local", objects = "big", concurrency = 16, rangeBytes = 262144}
    S3ReadScenario {id = 4, name = "range 1 MiB", kind = "range", dataset = "local", objects = "big", concurrency = 16, rangeBytes = 1048576}
    S3ReadScenario {id = 5, name = "local small get", kind = "get", dataset = "local", objects = "small", concurrency = 16}
    S3ReadScenario {id = 6, name = "range 4 MiB", kind = "range", dataset = "local", objects = "big", concurrency = 16, rangeBytes = 4194304}
    S3ReadScenario {id = 7, name = "range 16 MiB", kind = "range", dataset = "local", objects = "big", concurrency = 16, rangeBytes = 16777216}
    S3ReadScenario {id = 8, name = "big get concurrency 1", kind = "get", dataset = "local", objects = "big", concurrency = 1}
    S3ReadScenario {id = 9, name = "big get concurrency 4", kind = "get", dataset = "local", objects = "big", concurrency = 4}
    S3ReadScenario {id = 10, name = "big get concurrency 16", kind = "get", dataset = "local", objects = "big", concurrency = 16}
]

# The scenario ids each RunS3ReadScenarios step runs, in order. Every AzCli step signs in once and
# kubectl reuses that Entra ID login; a workload identity login in a pipeline task can fail after
# about an hour, so each step must finish well within that. In a full run scenarios 1-10 took 103
# minutes in all and scenario 7 alone 21 minutes; each of these groups took 33 minutes or less.
S3_READ_SCENARIO_GROUPS: [[int]] = [[1, 2, 3], [4, 5], [6, 7], [8, 9, 10]]

SeedS3ReadData = lambda serviceConnection: str, subscription: str, resourceGroup: str, localLocation: str, remoteLocation: str, localAccount: str, remoteAccount: str, workDir: str, resultDir: str, checksDir: str -> steps.Step {
    assert localAccount != remoteAccount, "the local and remote storage accounts must differ"
    azure.AzCli(
        serviceConnection
        "Create local and remote Blob datasets for S3 reads"
        S3ReadShellSetup(workDir, resultDir) + SecretCommands(workDir) + """
# Prints a container SAS for the account selected by AZURE_STORAGE_ACCOUNT/KEY.
# $1 container, $2 permissions, $3 lifetime in hours.
make_sas() {
    az storage container generate-sas \\
        --name "$1" \\
        --permissions "$2" \\
        --expiry "$(date -u -d "+$3 hours" +%Y-%m-%dT%H:%MZ)" \\
        --https-only 2> /dev/null |
        jq -er 'select(type == "string" and length > 0)' 2> /dev/null
}
# Exports $2 as a secret pipeline variable named $1; the value never reaches the log.
publish_secret() {
    local value="$2"
    value="\${value//'%'/'%AZP25'}"
    value="\${value//$'\\n'/'%0A'}"
    value="\${value//$'\\r'/'%0D'}"
    printf '##vso[task.setvariable variable=%s;issecret=true]%s\\n' "$1" "$value"
}
seed_account() {
    local account="$1" location="$2" index
    az storage account create \\
        --name "$account" \\
        --resource-group "${resourceGroup}" \\
        --subscription "${subscription}" \\
        --location "$location" \\
        --kind StorageV2 \\
        --sku Standard_LRS \\
        --https-only true \\
        --min-tls-version TLS1_2 \\
        --allow-blob-public-access false \\
        --hns false > /dev/null
    export AZURE_STORAGE_ACCOUNT="$account"
    AZURE_STORAGE_KEY="$(private_command az storage account keys list \\
        --account-name "$account" \\
        --resource-group "${resourceGroup}" \\
        --subscription "${subscription}" | jq -er '.[0].value')"
    export AZURE_STORAGE_KEY
    az storage container create \\
        --name s3-data \\
        --public-access off > /dev/null
    for ((index = 0; index < 16; index++)); do
        # Fixed per-object keys produce deterministic, nonzero 64 MiB payloads.
        head -c 67108864 /dev/zero |
            openssl enc -aes-256-ctr -K "$(printf '%064x' "$index")" \\
                -iv 00000000000000000000000000000000 > "${workDir}/blob.bin"
        az storage blob upload \\
            --container-name s3-data \\
            --name "$(printf 'object-%02d.bin' "$index")" \\
            --file "${workDir}/blob.bin" \\
            --overwrite false > /dev/null
    done
    rm -f -- "${workDir}/blob.bin"
    mkdir -p -- "${workDir}/small"
    for ((index = 0; index < 1024; index++)); do
        # Offset the key so small objects differ from the big ones; 1 MiB each.
        head -c 1048576 /dev/zero |
            openssl enc -aes-256-ctr -K "$(printf '%064x' "$((index + 16))")" \\
                -iv 00000000000000000000000000000000 > "${workDir}/small/$(printf 'obj-%04d.bin' "$index")"
    done
    # One batch upload: each single `az storage blob upload` costs about 2 s of fixed overhead.
    az storage blob upload-batch \\
        --destination s3-data \\
        --destination-path small \\
        --source "${workDir}/small" \\
        --overwrite false > /dev/null
    rm -rf -- "${workDir}/small"
    # --include m exposes metadata.hdi_isfolder; --num-results is explicit so a truncated listing cannot pass.
    az storage blob list \\
        --container-name s3-data \\
        --include m \\
        --num-results 5000 |
        jq -e -L "${checksDir}" 'include "checks"; validate_s3_read_dataset' > /dev/null
}
seed_account "${localAccount}" "${localLocation}"
# The reads cover the whole 240-minute job timeout; an 8-hour read SAS is twice that,
# so it cannot expire mid-run. The write SAS is used by SeedCheckpointSets, which runs soon
# after this step; 2 hours covers it.
local_data_sas="$(make_sas s3-data rl 8)" || fail "Could not generate the local data SAS; secret-bearing output withheld"
az storage container create \\
    --name checkpoint \\
    --public-access off > /dev/null
checkpoint_read_sas="$(make_sas checkpoint rl 8)" || fail "Could not generate the checkpoint read SAS; secret-bearing output withheld"
checkpoint_write_sas="$(make_sas checkpoint cw 2)" || fail "Could not generate the checkpoint write SAS; secret-bearing output withheld"
unset AZURE_STORAGE_KEY
seed_account "${remoteAccount}" "${remoteLocation}"
remote_data_sas="$(make_sas s3-data rl 8)" || fail "Could not generate the remote data SAS; secret-bearing output withheld"
unset AZURE_STORAGE_KEY
publish_secret LOCAL_DATA_SAS "$local_data_sas"
publish_secret REMOTE_DATA_SAS "$remote_data_sas"
publish_secret CHECKPOINT_READ_SAS "$checkpoint_read_sas"
publish_secret CHECKPOINT_WRITE_SAS "$checkpoint_write_sas"
unset local_data_sas remote_data_sas checkpoint_read_sas checkpoint_write_sas
jq -n \\
    --arg local_account "${localAccount}" --arg local_location "${localLocation}" \\
    --arg remote_account "${remoteAccount}" --arg remote_location "${remoteLocation}" \\
    '$ARGS.named + {container: "s3-data", big_object_count: 16, big_object_bytes: 67108864, small_object_count: 1024, small_object_bytes: 1048576}' \\
    > "${resultDir}/dataset.json"
"""
        stepName = "s3_read_dataset"
    )
}

PrepareWorkerNvme = lambda serviceConnection: str, manifest: str, workDir: str, resultDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Mount the local NVMe disk on every worker node"
        S3ReadShellSetup(workDir, resultDir) + """
kubectl create -f "${manifest}" > /dev/null
# One pod per workerpool node.
kubectl rollout status daemonset/alluxio-nvme -n kube-system --timeout=600s
[[ "$(kubectl get daemonset alluxio-nvme -n kube-system -o jsonpath='{.status.numberReady}')" == ${S3_READ_WORKER_COUNT} ]] ||
    fail "expected ${S3_READ_WORKER_COUNT} ready NVMe pods"
for pod in $(kubectl get pods -n kube-system -l app=alluxio-nvme -o name); do
    kubectl logs -n kube-system "$pod" | grep -q 'NVME READY /mnt/alluxio-nvme' ||
        fail "$pod did not report NVME READY"
done
"""
        stepName = "alluxio_nvme"
    )
}

# Worker counter of bytes read from the UFS (here Blob); its difference around an Alluxio run
# is what the workers fetched from Blob. Workers may label it and may print it in E-notation
# (for example 1.5E10); the awk sum in worker_ufs_bytes handles both.
UFS_READ_METRIC = "alluxio_external_data_read_bytes_total"

# Shared by every step that talks to the workers: worker_hosts prints the ready workers' S3 addresses
# and fails unless there are exactly S3_READ_WORKER_COUNT; worker_ufs_bytes prints the sum of
# UFS_READ_METRIC over the workers.
WORKER_SHELL = """
worker_hosts() {
    local pods ready_ips count
    pods="$(kubectl get pods -n alx-ns -l app.kubernetes.io/component=worker -o json)" ||
        fail "could not list the Alluxio worker pods"
    ready_ips="$(jq -c '[.items[] |
        select(.status.phase == "Running" and
            any(.status.conditions[]?; .type == "Ready" and .status == "True")) |
        .status.podIP | select(. != null and . != "")] | sort' <<< "$pods")"
    count="$(jq 'length' <<< "$ready_ips")"
    # A different count means a worker is missing or restarting.
    [[ "$count" == ${S3_READ_WORKER_COUNT} ]] || fail "expected ${S3_READ_WORKER_COUNT} ready Alluxio workers, found $count: $ready_ips"
    # 29998 is the Alluxio worker S3 port.
    jq -r 'map(. + ":29998") | join(",")' <<< "$ready_ips"
}
worker_ufs_bytes() {
    local workers worker count=0 total=0 value
    workers="$(kubectl get pods -n alx-ns -l app.kubernetes.io/component=worker -o jsonpath='{.items[*].metadata.name}')"
    for worker in $workers; do
        value="$(kubectl get --raw "/api/v1/namespaces/alx-ns/pods/$worker:30000/proxy/metrics/" |
            awk -v name="${UFS_READ_METRIC}" '
                $1 == name || index($1, name "{") == 1 { sum += $NF; found = 1 }
                END { if (!found) exit 1; printf "%.0f", sum }')" ||
            fail "worker $worker does not expose ${UFS_READ_METRIC}"
        total=$((total + value))
        count=$((count + 1))
    done
    (( count == ${S3_READ_WORKER_COUNT} )) || fail "expected ${S3_READ_WORKER_COUNT} Alluxio workers for the metrics scrape, found $count"
    printf '%s\\n' "$total"
}
"""

# The base redact only knows the license and BLOB_SAS, so this one masks the four SAS variables.
S3ReadSetup = lambda workDir: str, resultDir: str -> str {
    S3ReadShellSetup(workDir, resultDir) + SecretCommands(workDir) + WORKER_SHELL + """
redact() {
    local line secret
    while IFS= read -r line || [[ -n "$line" ]]; do
        for secret in "\\${LOCAL_DATA_SAS:-}" "\\${REMOTE_DATA_SAS:-}" "\\${CHECKPOINT_READ_SAS:-}" "\\${CHECKPOINT_WRITE_SAS:-}"; do
            if [[ -n "$secret" ]]; then line="\\${line//"$secret"/<redacted>}"; fi
        done
        printf '%s\\n' "$line"
    done
}
"""
}

CreateS3ReadClients = lambda serviceConnection: str, manifest: str, script: str, workDir: str, resultDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Create the S3 read client pods"
        S3ReadSetup(workDir, resultDir) + """
for variable in LOCAL_DATA_SAS REMOTE_DATA_SAS CHECKPOINT_READ_SAS CHECKPOINT_WRITE_SAS; do
    require_secret "$variable"
done
kubectl create configmap s3c-script -n alx-ns --from-file=s3c.sh="${script}" > /dev/null
# Process substitution keeps every SAS off argv and off disk; the secret is created, never applied.
kubectl create secret generic s3c-sas -n alx-ns \\
    --from-file=local-data=<(printf '%s' "$LOCAL_DATA_SAS") \\
    --from-file=remote-data=<(printf '%s' "$REMOTE_DATA_SAS") \\
    --from-file=checkpoint-read=<(printf '%s' "$CHECKPOINT_READ_SAS") \\
    --from-file=checkpoint-write=<(printf '%s' "$CHECKPOINT_WRITE_SAS") \\
    > /dev/null 2> >(redact >&2)
for index in $(seq 1 ${S3_READ_CLIENT_COUNT}); do
    patch="$(jq -n --arg name "s3c-$index" '{metadata: {name: $name}}')"
    pod="$(kubectl patch --local --type=merge -f "${manifest}" -p "$patch" -o yaml)"
    printf '%s\\n' "$pod" | kubectl create --dry-run=server --validate=strict -f - > /dev/null
    printf '%s\\n' "$pod" | kubectl create -f - > /dev/null
done
kubectl wait -n alx-ns --for=condition=Ready pod -l app=s3c --timeout=600s
# The anti-affinity rule must have put the client pods on different nodes.
kubectl get pods -n alx-ns -l app=s3c -o json |
    jq -e '[.items[].spec.nodeName] | unique | length == ${S3_READ_CLIENT_COUNT}' > /dev/null ||
    fail "the ${S3_READ_CLIENT_COUNT} client pods are not on ${S3_READ_CLIENT_COUNT} different nodes"
key_script="$(cat <<'KEYS'
set -eu
seq 0 15 | awk '{printf "object-%02d.bin\\n", $1}' > /tmp/big.txt
seq 0 1023 | awk '{printf "small/obj-%04d.bin\\n", $1}' > /tmp/small.txt
for set in 1 2 3 4 5 6; do
    seq 0 7 | awk -v set="$set" '{printf "set-%d/part-%d.bin\\n", set, $1}' > "/tmp/checkpoint-$set.txt"
done
KEYS
)"
for index in $(seq 1 ${S3_READ_CLIENT_COUNT}); do
    kubectl exec -n alx-ns "s3c-$index" -c s3c -- sh -c "$key_script"
done
"""
        stepName = "s3_read_clients"
        env = {
            LOCAL_DATA_SAS = "$(LOCAL_DATA_SAS)"
            REMOTE_DATA_SAS = "$(REMOTE_DATA_SAS)"
            CHECKPOINT_READ_SAS = "$(CHECKPOINT_READ_SAS)"
            CHECKPOINT_WRITE_SAS = "$(CHECKPOINT_WRITE_SAS)"
        }
    )
}

# Checkpoint objects are set-<1..6>/part-<0..7>.bin; set n is written by pod s3c-((n - 1) % S3_READ_CLIENT_COUNT + 1).
SeedCheckpointSets = lambda serviceConnection: str, localAccount: str, workDir: str, resultDir: str, checksDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Generate the checkpoint sets in the clients"
        S3ReadSetup(workDir, resultDir) + """
seed_script="$(cat <<'SEED'
set -eu
umask 077
account=$1
shift
sas="$(cat /sas/checkpoint-write)"
trap 'rm -f /scratch/*.bin /scratch/*.curl' EXIT
upload_part() {
    local set="$1" part="$2"
    local file="/scratch/set-$set-part-$part.bin" config="/scratch/set-$set-part-$part.curl"
    # /dev/urandom, not openssl: the client image has no openssl, and reads only need incompressible bytes.
    dd if=/dev/urandom of="$file" bs=1048576 count=2048 2> /dev/null
    [ "$(wc -c < "$file")" -eq 2147483648 ] || { echo "ALLUXIO S3 READ FAILED: short temp file $file" >&2; exit 1; }
    # The SAS goes into a 0600 curl config, not onto argv. Put Blob needs a Content-Length,
    # so the body is a file (-T), not a pipe; x-ms-version 2019-12-12 allows a single 5000 MiB Put Blob.
    printf 'url = "https://%s.blob.core.windows.net/checkpoint/set-%s/part-%s.bin?%s"\\n' \\
        "$account" "$set" "$part" "$sas" > "$config"
    # Each 2 GiB attempt is capped at 30 minutes and no retry starts after 30 minutes,
    # so a stalled upload fails the step long before the job timeout.
    curl --silent --show-error --fail --retry 3 --retry-delay 5 --max-time 1800 --retry-max-time 1800 --config "$config" \\
        -T "$file" \\
        -H 'x-ms-blob-type: BlockBlob' \\
        -H 'x-ms-version: 2019-12-12' > /dev/null || { echo "ALLUXIO S3 READ FAILED: upload of set-$set/part-$part failed" >&2; exit 1; }
    rm -f "$file" "$config"
}
for set in "$@"; do
    pids=""
    for part in 0 1 2 3 4 5 6 7; do
        upload_part "$set" "$part" &
        pids="$pids $!"
    done
    for pid in $pids; do
        wait "$pid" || { echo "ALLUXIO S3 READ FAILED: set $set did not finish uploading" >&2; exit 1; }
    done
    echo "set-$set uploaded"
done
SEED
)"
# A kubectl exec stream can drop during a long upload and still return 0 while the upload keeps running
# in the pod. So the upload runs detached in the pod (setsid, stdio not tied to the exec) and writes its
# log and exit status to /scratch; short execs poll for the status file.
# The sets a pod printed as uploaded are then counted against the sets assigned to it.
seed_run='sh /scratch/seed.sh "$@" > /scratch/seed.log 2>&1
echo $? > /scratch/seed.rc'
seed_pod() {
    local index="$1" rc="" deadline
    local pod="s3c-$index"
    shift
    # One short exec writes both scripts (passed as arguments, not stdin) and starts the upload detached.
    kubectl exec -n alx-ns "$pod" -c s3c -- sh -c 'printf "%s\\n" "$1" > /scratch/seed.sh
        printf "%s\\n" "$2" > /scratch/seed-run.sh
        shift 2
        rm -f /scratch/seed.rc /scratch/seed.log
        setsid sh /scratch/seed-run.sh "$@" < /dev/null > /dev/null 2>&1 &' sh "$seed_script" "$seed_run" "${localAccount}" "$@"
    # A pod uploads at most 2 sets of 16 GiB, which takes a few minutes; 40 minutes is a generous bound.
    deadline=$((SECONDS + 2400))
    until rc="$(kubectl exec -n alx-ns "$pod" -c s3c -- cat /scratch/seed.rc 2> /dev/null)"; do
        if (( SECONDS >= deadline )); then
            rc=timeout
            break
        fi
        sleep 15
    done
    kubectl exec -n alx-ns "$pod" -c s3c -- cat /scratch/seed.log 2>&1 | redact > "${resultDir}/checkpoint-seed-$pod.log" || true
    echo "$rc" > "${workDir}/checkpoint-seed-$pod.rc"
}
pids=()
assigned=()
for index in $(seq 1 ${S3_READ_CLIENT_COUNT}); do
    sets=""
    for set in 1 2 3 4 5 6; do
        if (( (set - 1) % ${S3_READ_CLIENT_COUNT} + 1 == index )); then
            sets="$sets $set"
        fi
    done
    assigned[index]="$sets"
    rm -f "${workDir}/checkpoint-seed-s3c-$index.rc"
    seed_pod "$index" $sets &
    pids+=($!)
done
for pid in "\\${pids[@]}"; do
    wait "$pid" || true
done
seed_failed=0
for index in $(seq 1 ${S3_READ_CLIENT_COUNT}); do
    pod="s3c-$index"
    log="${resultDir}/checkpoint-seed-$pod.log"
    rc="$(cat "${workDir}/checkpoint-seed-$pod.rc" 2> /dev/null || echo missing)"
    uploaded="$(sed -n 's/^\\(set-[0-9][0-9]*\\) uploaded$/\\1/p' "$log" | paste -sd, -)"
    count="$(grep -c '^set-[0-9]* uploaded$' "$log" || true)"
    want="$(wc -w <<< "\\${assigned[index]}" | tr -d ' ')"
    echo "$pod: exit $rc, uploaded sets: \\${uploaded:-none}"
    if [[ "$rc" != 0 ]] || (( count < want )); then
        echo "ALLUXIO S3 READ FAILED: $pod uploaded $count of $want assigned sets (exit $rc)" >&2
        seed_failed=1
    fi
done
(( seed_failed == 0 )) || exit 1
list_script="$(cat <<'LIST'
set -eu
umask 077
sas="$(cat /sas/checkpoint-read)"
trap 'rm -f /scratch/list.curl' EXIT
printf 'url = "https://%s.blob.core.windows.net/checkpoint?restype=container&comp=list&include=metadata&maxresults=5000&%s"\\n' \\
    "$1" "$sas" > /scratch/list.curl
# One tab-separated line per blob: name, size, hdi_isfolder metadata. A non-empty NextMarker means a truncated listing.
curl --silent --show-error --fail --max-time 120 --config /scratch/list.curl -H 'x-ms-version: 2019-12-12' |
    awk 'BEGIN { RS = "<" }
        { gsub(/[\\r\\n]/, "") }
        /^Blob>/ { name = ""; size = ""; folder = "" }
        /^Name>/ { name = substr($0, 6) }
        /^Content-Length>/ { size = substr($0, 16) }
        /^hdi_isfolder>/ { folder = substr($0, 14) }
        /^NextMarker>/ { print "#truncated" }
        /^\\/Blob>/ { printf "%s\\t%s\\t%s\\n", name, size, folder }'
LIST
)"
listing="$(kubectl exec -n alx-ns s3c-1 -c s3c -- sh -c "$list_script" sh "${localAccount}" 2> >(redact >&2))" ||
    fail "could not list the checkpoint container"
# Keep what the container holds (name, size, marker; no SAS) so a failed validation can be inspected.
printf '%s\\n' "$listing" | grep -v '^$' > "${resultDir}/checkpoint-listing.tsv" || true
echo "checkpoint container: $(wc -l < "${resultDir}/checkpoint-listing.tsv" | tr -d ' ') blobs, distinct sizes: $(cut -f2 "${resultDir}/checkpoint-listing.tsv" | sort -u | paste -sd, -)"
[[ "$listing" != *'#truncated'* ]] || fail "the checkpoint listing is truncated"
# Each listing line is name, size and hdi_isfolder metadata; checks.jq decides whether the container is right.
printf '%s\\n' "$listing" | jq -R -s -L "${checksDir}" '
    include "checks";
    [split("\\n")[] | select(length > 0) | split("\\t") | {
        name: .[0],
        properties: {contentLength: (.[1] | tonumber)},
        metadata: (if .[2] == "" then null else {hdi_isfolder: .[2]} end)}]
    | validate_checkpoint_dataset' > /dev/null || fail "checkpoint container validation failed"
jq -n '{checkpoint_sets: 6, checkpoint_parts_per_set: 8, checkpoint_object_count: 48, checkpoint_object_bytes: 2147483648}' \\
    > "${resultDir}/checkpoint.json"
"""
        stepName = "s3_read_checkpoint"
        env = {
            CHECKPOINT_READ_SAS = "$(CHECKPOINT_READ_SAS)"
            CHECKPOINT_WRITE_SAS = "$(CHECKPOINT_WRITE_SAS)"
        }
    )
}

# Runs the scenarios with the given ids (one group of S3_READ_SCENARIO_GROUPS) in pod s3c-1,
# against Alluxio and direct Blob. The first group also starts runs/index.jsonl and warms both
# datasets; later groups append to that index. Dataset local is Alluxio bucket "blob" (mount
# /blob) and the local account; remote is bucket "xregion" (mount /xregion) and the remote account.
RunS3ReadScenarios = lambda serviceConnection: str, localAccount: str, remoteAccount: str, workDir: str, resultDir: str, checksDir: str, ids: [int] -> steps.Step {
    assert localAccount != remoteAccount, "the local and remote storage accounts must differ"
    scenarios = [scenario for scenario in S3_READ_SCENARIOS if scenario.id in ids]
    assert [scenario.id for scenario in scenarios] == ids, "ids must be scenario ids in S3_READ_SCENARIOS order"
    first = ids[0] == S3_READ_SCENARIOS[0].id
    label = "${ids[0]}-${ids[-1]}" if len(ids) > 1 else "${ids[0]}"
    # Per dataset: Alluxio bucket, mount path, Blob account and the SAS file in the client pods (see CreateS3ReadClients).
    datasets = {
        local = {bucket = "blob", mount = "/blob", account = localAccount, sas = "local-data"}
        remote = {bucket = "xregion", mount = "/xregion", account = remoteAccount, sas = "remote-data"}
    }
    scenario_call = lambda scenario: S3ReadScenario -> str {
        dataset = datasets[scenario.dataset]
        big_get = scenario.kind == "get" and scenario.objects == "big"
        object_bytes = 67108864 if scenario.objects == "big" else 1048576
        request_bytes = scenario.rangeBytes if scenario.kind == "range" else object_bytes
        # Each worker runs its requests in batches, one curl run per batch. Every batch opens its connections
        # and sends a warm-up HEAD per host (see s3c.sh); that is kept out of the latency percentiles but not
        # out of the run's wall time, so larger batches spread it over more requests. A worker starts no new
        # batch after 60 s, so the last batch in flight overruns the window. Size batches by bytes, about
        # 256 MiB per batch and at most 50 requests: the slowest requests seen in a full run were
        # cross-region 64 MiB GETs from Blob at 16 concurrent requests (p99 5.7 s), so a batch of four ends
        # within about 23 s, inside the 30 s checks.jq allows for the rest of a batch.
        # Examples: 256 KiB, 1 MiB and 4 MiB requests 50, 16 MiB 16, a 64 MiB get 4.
        batch = max(min(268435456 // request_bytes, 50), 1)
        # s3c.sh fails when the budget runs out before 60 s, so it must exceed the fastest scenario:
        # 100000 requests per worker over 60 s is about 1,667 requests/s per worker. A 64 MiB get
        # cannot come close to that (about 10 per second from the cache at one request at a time),
        # so its budget is small: 2000, a whole number of batches of four.
        budget = 2000 if big_get else 100000
        # The scenario's fields go into runs/index.jsonl and from there into summary.json.
        metadata = json.encode({
            id = scenario.id
            name = scenario.name
            kind = scenario.kind
            dataset = scenario.dataset
            concurrency = scenario.concurrency
            rangeBytes = scenario.rangeBytes
        })
        "run_scenario '${metadata}' ${scenario.kind} ${dataset.bucket} ${dataset.account} ${dataset.sas} /tmp/${scenario.objects}.txt ${object_bytes} ${scenario.concurrency} ${scenario.rangeBytes} ${batch} ${budget}"
    }
    scenario_calls = "\n".join([scenario_call(scenario) for scenario in scenarios])
    azure.AzCli(
        serviceConnection
        "Run S3 read scenarios ${label} against Alluxio and Blob"
        S3ReadSetup(workDir, resultDir) + """
mkdir -p -- "${resultDir}/runs"
""" + (''': > "${resultDir}/runs/index.jsonl"
''' if first else '''[[ -s "${resultDir}/runs/index.jsonl" ]] || fail "the first scenario group has not run"
''') + """
alluxio() {
    kubectl exec -n alx-ns alluxio-coordinator-0 \\
        -c alluxio-coordinator -- alluxio "$@"
}
# Runs s3c.sh once in client pod s3c-1; the JSON result goes to stdout, redacted.
# $1 side (alluxio|blob), then the scenario parameters of run_scenario after the metadata.
run_s3c() {
    local side="$1" kind="$2" bucket="$3" account="$4" sas="$5" keys="$6" object_bytes="$7"
    local concurrency="$8" range_bytes="$9" batch="\${10}" budget="\${11}" duration="\${12}" hosts
    local args=(MODE="$side" KIND="$kind" CONCURRENCY="$concurrency" DURATION_SECONDS="$duration"
        KEYS_FILE="$keys" OBJECT_BYTES="$object_bytes" RANGE_BYTES="$range_bytes"
        BATCH_REQUESTS="$batch" MAX_REQUESTS_PER_WORKER="$budget")
    if [[ "$side" == alluxio ]]; then
        # Re-read the worker list for every run: a worker that restarted since the last run must fail the step.
        hosts="$(worker_hosts)"
        args+=(HOSTS="$hosts" EXPECTED_HOSTS=${S3_READ_WORKER_COUNT} BUCKET="$bucket")
    else
        args+=(ACCOUNT="$account" CONTAINER=s3-data SAS_FILE="/sas/$sas")
    fi
    kubectl exec -n alx-ns s3c-1 -c s3c -- env "\${args[@]}" sh /scripts/s3c.sh 2> >(redact >&2)
}
# $1 scenario metadata (JSON), $2 side, $3 rep, then run_s3c arguments after the side.
# s3c.sh already retries every failed request, with the same policy on both sides, so a run is not
# repeated: an error left after those retries, on either side, fails the step.
# Both datasets are loaded and checked as fully cached before scenario 1, and every scenario reads one of
# them, so every Alluxio rep must be served from the cache. Alluxio can fall back to reading Blob while
# every response still looks fine, so the workers' UFS-read counter is read before and after each Alluxio
# rep; if they read more than 1% of the bytes the client read (served_from_cache in checks.jq), the step
# fails. The counters go into the rep's index entry as worker_ufs, and from there into summary.json.
run_and_record() {
    local scenario="$1" side="$2" rep="$3" id start end out status=0 run_file ufs_before ufs_after worker_ufs='{}'
    id="$(jq -r '.id' <<< "$scenario")"
    shift 3
    run_file="${resultDir}/runs/$id-$side-$rep.json"
    if [[ "$side" == alluxio ]]; then
        ufs_before="$(worker_ufs_bytes)"
    fi
    start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    out="$(run_s3c "$side" "$@" 60)" || status=$?
    end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    # s3c.sh prints its JSON result before it fails; keep that result for diagnosis.
    printf '%s\\n' "$out" | redact > "$run_file"
    if (( status != 0 )) || ! jq -e -L "${checksDir}" 'include "checks"; validate_s3c_run' "$run_file" > /dev/null; then
        fail "scenario $id $side rep $rep failed or produced an invalid result"
    fi
    if [[ "$side" == alluxio ]]; then
        ufs_after="$(worker_ufs_bytes)"
        worker_ufs="$(jq -nc --argjson before "$ufs_before" --argjson after "$ufs_after" \\
            '{worker_ufs: {before: $before, after: $after, bytes: ($after - $before)}}')"
        jq -e -L "${checksDir}" --argjson ufs_bytes "$((ufs_after - ufs_before))" \\
            'include "checks"; served_from_cache($ufs_bytes)' "$run_file" > /dev/null ||
            fail "scenario $id alluxio rep $rep: the workers read $((ufs_after - ufs_before)) bytes from Blob while the client read $(jq -r '.bytes' "$run_file"); more than 1% (or a negative count, from a restarted worker) means the rep was not served from the preloaded cache"
    fi
    jq -nc --argjson scenario "$scenario" --arg side "$side" --argjson rep "$rep" --arg started "$start" --arg ended "$end" \\
        --argjson worker_ufs "$worker_ufs" \\
        '$scenario + {side: $side, rep: $rep, start: $started, end: $ended} + $worker_ufs' >> "${resultDir}/runs/index.jsonl"
}
# $1 scenario metadata (JSON), then the arguments of run_s3c after the side.
run_scenario() {
    local scenario="$1" rep
    shift
    # Alternate Alluxio and Blob reps so that drift over time affects both sides.
    for rep in 1 2 3; do
        run_and_record "$scenario" alluxio "$rep" "$@"
        run_and_record "$scenario" blob "$rep" "$@"
    done
}
# $1 dataset name, $2 mount path.
# The dataset is warmed with Alluxio's distributed load, not with client reads. With
# alluxio.worker.s3.redirect.enabled=false a read through a worker that does not own the file is
# relayed and does not populate the cache, so one pass of client reads cannot cache every file.
warm_dataset() {
    local name="$1" mount="$2" attempt state failed deadline
    alluxio job load --path "$mount" --submit | redact > "${resultDir}/preload-submit-$name.txt"
    # Bound the wait to 10 minutes; a load still not finished then fails the step.
    deadline=$((SECONDS + 600))
    while :; do
        alluxio job load --path "$mount" --progress | redact > "${resultDir}/preload-$name.txt"
        # A job waits (WAITING) until the scheduler picks it up and may verify (VERIFYING) before it ends.
        # The state can be followed by a note, as in "Job State: SUCCEEDED (3 directories failed to index; ...)",
        # so only the first word is the state.
        state="$(sed -nE 's/^[[:space:]]*Job State:[[:space:]]*([A-Z_]+).*$/\\1/p' "${resultDir}/preload-$name.txt")"
        case "$state" in
            CREATED|WAITING|RUNNING|VERIFYING|SUCCEEDED) ;;
            *) fail "preload of the $name dataset failed or returned an unrecognized job state" ;;
        esac
        failed="$(sed -nE 's/^[[:space:]]*Files Failed:[[:space:]]*([0-9]+)[[:space:]]*$/\\1/p' "${resultDir}/preload-$name.txt")"
        [[ "$failed" == 0 ]] || fail "preload of the $name dataset must report zero failed files"
        [[ "$state" == SUCCEEDED ]] && break
        (( SECONDS < deadline )) || fail "preload of the $name dataset did not finish within 10 minutes"
        sleep 10
    done
    # --limit 1041 exceeds the 1,040 objects (16 big + 1,024 small), so the report is not truncated.
    # Cache population can lag the end of the load job, so poll: at most 6 checks 10 s apart (about 1 minute),
    # then a real shortfall fails the step.
    for attempt in 1 2 3 4 5 6; do
        if alluxio fs check-cached --path "$mount" --recursive --limit 1041 | redact > "${resultDir}/cache-$name.txt" &&
            jq -Rse -L "${checksDir}" 'include "checks"; validate_all_cached' "${resultDir}/cache-$name.txt" > /dev/null; then
            return 0
        fi
        (( attempt == 6 )) || sleep 10
    done
    fail "the $name dataset is not fully cached after 6 checks over about a minute"
}
""" + ("warm_dataset local ${datasets.local.mount}\nwarm_dataset remote ${datasets.remote.mount}\n" if first else "") + scenario_calls + "\n"
        stepName = "s3_read_scenarios_" + label.replace("-", "_")
        env = {
            LOCAL_DATA_SAS = "$(LOCAL_DATA_SAS)"
            REMOTE_DATA_SAS = "$(REMOTE_DATA_SAS)"
            CHECKPOINT_READ_SAS = "$(CHECKPOINT_READ_SAS)"
            CHECKPOINT_WRITE_SAS = "$(CHECKPOINT_WRITE_SAS)"
        }
    )
}

# Scenarios 11 and 12: all client pods read the same 8 x 2 GiB checkpoint set at the same time.
# Alluxio reads sets 1-3 (bucket ckpt), direct Blob reads sets 4-6, one set per rep. The bytes the
# Blob account served are attributed to each rep from the Azure Monitor Egress metric.
# It needs no SAS: the SAS files are mounted in the client pods, so the step handles no secret
# and needs no redact.
RunCheckpointLoad = lambda serviceConnection: str, subscription: str, resourceGroup: str, localAccount: str, workDir: str, resultDir: str, checksDir: str -> steps.Step {
    assert localAccount != "", "the local storage account name must be set"
    azure.AzCli(
        serviceConnection
        "Load checkpoints from ${S3_READ_CLIENT_COUNT} clients and attribute Blob egress"
        S3ReadShellSetup(workDir, resultDir) + WORKER_SHELL + """
checkpoint_dir="${resultDir}/checkpoint"
mkdir -p -- "$checkpoint_dir"
: > "$checkpoint_dir/index.jsonl"
: > "$checkpoint_dir/worker-ufs.jsonl"
# 8 objects of 2 GiB (2147483648 bytes) are read once per pod.
expected_bytes=17179869184
# $1 side, $2 rep, $3 pod, then the s3c.sh environment. Runs in the background, one per pod.
read_one() {
    local side="$1" rep="$2" pod="$3" start end out
    shift 3
    start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if ! out="$(kubectl exec -n alx-ns "$pod" -c s3c -- env "$@" sh /scripts/s3c.sh)"; then
        # s3c.sh prints its JSON result before it fails; keep it. It holds only counters, no SAS.
        printf '%s\\n' "$out" > "$checkpoint_dir/$side-$rep-$pod.json"
        exit 1
    fi
    end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s\\n' "$out" > "$checkpoint_dir/$side-$rep-$pod.json"
    jq -nc --arg side "$side" --argjson rep "$rep" --arg pod "$pod" --arg started "$start" --arg ended "$end" \\
        '{side: $side, rep: $rep, pod: $pod, start: $started, end: $ended}' > "$checkpoint_dir/$side-$rep-$pod.index"
}
# $1 side (alluxio|blob), $2 rep, $3 checkpoint set. All client pods read the set at the same time.
read_set() {
    local side="$1" rep="$2" set="$3" index pid status=0 pids=()
    local args=(KIND=onepass CONCURRENCY=8 KEYS_FILE="/tmp/checkpoint-$set.txt"
        OBJECT_BYTES=2147483648 BATCH_REQUESTS=1)
    if [[ "$side" == alluxio ]]; then
        # Re-read the worker list for every rep: a restarted worker must fail the step.
        args+=(MODE=alluxio HOSTS="$(worker_hosts)" EXPECTED_HOSTS=${S3_READ_WORKER_COUNT} BUCKET=ckpt)
    else
        args+=(MODE=blob ACCOUNT="${localAccount}" CONTAINER=checkpoint SAS_FILE=/sas/checkpoint-read)
    fi
    for index in $(seq 1 ${S3_READ_CLIENT_COUNT}); do
        # Every pod reads the same keys; each starts at a different worker, so on the Alluxio side every
        # worker serves the same share of the requests (with 5 pods and 5 workers, 8 each).
        read_one "$side" "$rep" "s3c-$index" "\\${args[@]}" HOST_OFFSET=$((index - 1)) &
        pids+=($!)
    done
    for pid in "\\${pids[@]}"; do
        wait "$pid" || status=1
    done
    (( status == 0 )) || fail "checkpoint $side rep $rep: at least one client failed"
    for index in $(seq 1 ${S3_READ_CLIENT_COUNT}); do
        jq -e -L "${checksDir}" --argjson expected "$expected_bytes" \\
            'include "checks"; validate_s3c_run | .bytes == $expected' \\
            "$checkpoint_dir/$side-$rep-s3c-$index.json" > /dev/null ||
            fail "checkpoint $side rep $rep s3c-$index produced an invalid result"
        cat "$checkpoint_dir/$side-$rep-s3c-$index.index" >> "$checkpoint_dir/index.jsonl"
        rm -f -- "$checkpoint_dir/$side-$rep-s3c-$index.index"
    done
}
resource_id="$(az storage account show \\
    --name "${localAccount}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --query id \\
    --output tsv)"
[[ -n "$resource_id" ]] || fail "could not resolve the resource ID of ${localAccount}"
# Egress is per storage account and arrives about a minute late, and scenarios 1-10 just read this
# account; wait so their last reads fall before the first rep's window.
sleep 180
step_start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
for rep in 1 2 3; do
    before="$(worker_ufs_bytes)"
    read_set alluxio "$rep" "$rep"
    after="$(worker_ufs_bytes)"
    jq -nc --argjson rep "$rep" --argjson before "$before" --argjson after "$after" \\
        '{rep: $rep, before: $before, after: $after, bytes: ($after - $before)}' >> "$checkpoint_dir/worker-ufs.jsonl"
    # Azure Monitor reports Egress per minute; runs at least 70 s apart start in different minute windows.
    sleep 70
    read_set blob "$rep" "$((rep + 3))"
    (( rep == 3 )) || sleep 70
done
last_rep_end=$SECONDS
: > "$checkpoint_dir/runs.jsonl"
for file in "$checkpoint_dir"/*-s3c-*.json; do
    name="$(basename "$file" .json)"
    jq -c --arg name "$name" \\
        '($name | capture("^(?<side>[a-z]+)-(?<rep>[0-9]+)-(?<pod>.+)$")) as $id
         | {side: $id.side, rep: ($id.rep | tonumber), pod: $id.pod, wall_seconds: .wall_seconds, retries: .retries}' \\
        "$file" >> "$checkpoint_dir/runs.jsonl"
done
# Egress minute metrics arrive about 1 minute late; the first query waits 3 minutes after the last rep.
# Then query every 60 s until every window has data and checks.jq's bounds hold, for up to 10 minutes
# after the last rep. egress.json ends up as the output of the last query.
sleep 180
while :; do
    step_end="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    az monitor metrics list \\
        --resource "$resource_id" \\
        --metric Egress \\
        --interval PT1M \\
        --aggregation Total \\
        --start-time "$step_start" \\
        --end-time "$step_end" > "$checkpoint_dir/egress.json"
    if jq -n -L "${checksDir}" \\
        --slurpfile index "$checkpoint_dir/index.jsonl" \\
        --slurpfile runs "$checkpoint_dir/runs.jsonl" \\
        --slurpfile worker_ufs "$checkpoint_dir/worker-ufs.jsonl" \\
        --slurpfile metrics "$checkpoint_dir/egress.json" \\
        'include "checks"; {index: $index, runs: $runs, worker_ufs: $worker_ufs, metrics: $metrics[0]} | checkpoint_summary' \\
        > "$checkpoint_dir/summary.json" 2> "$checkpoint_dir/summary.err"; then
        break
    fi
    if (( SECONDS >= last_rep_end + 600 )); then
        cat "$checkpoint_dir/summary.err" >&2
        fail "could not attribute Blob egress within 10 minutes of the last rep; see $checkpoint_dir/egress.json"
    fi
    echo "Blob egress is not complete yet: $(tail -n 1 "$checkpoint_dir/summary.err")"
    sleep 60
done
rm -f -- "$checkpoint_dir/summary.err"
"""
        stepName = "s3_read_checkpoint_load"
    )
}

# Merges the scenario 1-10 medians with the checkpoint summary into summary.json.
# runs/index.jsonl has one entry per run (scenario fields, side, rep, start, end); each entry is
# merged with runs/<id>-<side>-<rep>.json.
SummarizeS3Read = lambda workDir: str, resultDir: str, checksDir: str -> steps.Bash {
    steps.Bash {
        name = "s3_read_summary"
        displayName = "Summarize the S3 read results"
        bash = S3ReadShellSetup(workDir, resultDir) + """
runs_file="${workDir}/summary-runs.jsonl"
: > "$runs_file"
while IFS= read -r entry; do
    run_file="${resultDir}/runs/$(jq -r '"\\(.id)-\\(.side)-\\(.rep)"' <<< "$entry").json"
    jq -c --argjson entry "$entry" '$entry + .' "$run_file" >> "$runs_file"
done < "${resultDir}/runs/index.jsonl"
[[ -s "${resultDir}/checkpoint/summary.json" ]] || fail "the checkpoint summary is missing"
jq -s -L "${checksDir}" 'include "checks"; scenario_summary' "$runs_file" > "${workDir}/scenarios.json"
# Scenarios 1-10 must all be present.
jq -e 'map(.id) == [range(1; 11)]' "${workDir}/scenarios.json" > /dev/null ||
    fail "the summary does not cover exactly scenarios 1-10"
jq -n \\
    --slurpfile scenarios "${workDir}/scenarios.json" \\
    --slurpfile checkpoint "${resultDir}/checkpoint/summary.json" \\
    '{scenarios: $scenarios[0], checkpoint: $checkpoint[0]}' > "${resultDir}/summary.json"
rm -f -- "$runs_file" "${workDir}/scenarios.json"
"""
    }
}

# Runs last before the results are published. A SAS signature (sig=) anywhere in the result
# directory means a secret leaked, so the directory is emptied and the job fails.
RefuseSasInResults = lambda workDir: str, resultDir: str -> steps.Bash {
    steps.Bash {
        name = "s3_read_sas_check"
        displayName = "Refuse to publish results that contain a SAS signature"
        condition = "always()"
        bash = S3ReadShellSetup(workDir, resultDir) + """
if grep -rq 'sig=' "${resultDir}"; then
    find "${resultDir}" -mindepth 1 -delete
    echo "ALLUXIO S3 READ FAILED: a SAS signature (sig=) was present in the results; the results were deleted, not published" >&2
    exit 1
fi
"""
    }
}
