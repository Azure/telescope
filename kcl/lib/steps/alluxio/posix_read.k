import azure_pipelines.ap.steps
import json
import lib.const
import lib.steps.azure

# "smoke" shrinks every size below for a quick end-to-end check; anything else must be unset or "full".
PosixScaled = lambda scale: str, full: int, smoke: int -> int {
    assert scale in ["smoke", "full"], "scale must be smoke or full, got ${scale}"
    smoke if scale == "smoke" else full
}

POSIX_SCALE = option("scale", default="full")

# Node counts: the cache nodes run Alluxio workers or DACS, the client nodes run one elbencho
# service pod each, the system pool runs the cluster components.
POSIX_CACHE_COUNT = PosixScaled(POSIX_SCALE, 5, 2)
POSIX_CLIENT_COUNT = PosixScaled(POSIX_SCALE, 5, 2)
POSIX_SYSTEM_COUNT = PosixScaled(POSIX_SCALE, 3, 2)

# Dataset sizes. All files are flat, without directories.
# - Hot pool: 480 x 512 MiB = 240 GiB, more than the memory of the five client nodes together (5 x 32 GiB =
#   160 GiB); an even share is 48 GiB per client, so no client's page cache or BlobFuse2 block cache can hold
#   its share and the hot reads measure the cache layer.
# - Cold: 25 files of 2 GiB (50 GiB) per rep that nothing has read before, of which a rep reads 1.5 GiB in 64 KiB
#   reads at random offsets. Each system fetches whole units from Blob, so a read can hit a unit that an earlier
#   read of the same rep fetched: at random offsets about 10,900 of the set's 12,800 Alluxio pages of 4 MiB (the
#   worker default) are fetched and about 56% of the reads are such hits, against about 19,500 of its 51,200
#   BlobFuse2 and DACS blocks of 1 MiB and about 21% hits. Alluxio also fetches more bytes per miss (about 43 GiB
#   per rep against about 19 GiB, before any read-ahead).
# - Concurrent reads: 8 files of 2 GiB (16 GiB) per rep, which every client reads in full; a cache has to fetch
#   them from Blob only once for all clients.
# - Re-read: one 8 GiB file, less than a client node's 32 GiB of memory, so the second read can be served from
#   the page cache.
POSIX_HOT_FILES = PosixScaled(POSIX_SCALE, 480, 16)
POSIX_HOT_FILE_MIB = PosixScaled(POSIX_SCALE, 512, 64)
POSIX_COLD_FILES = PosixScaled(POSIX_SCALE, 25, 4)
POSIX_CC_FILES = PosixScaled(POSIX_SCALE, 8, 2)
POSIX_BIG_FILE_GIB = PosixScaled(POSIX_SCALE, 2, 1)
POSIX_REREAD_GIB = PosixScaled(POSIX_SCALE, 8, 1)

# Measurement window of one hot repetition, and how many repetitions each side runs per scenario.
POSIX_REP_SECONDS = PosixScaled(POSIX_SCALE, 60, 10)
POSIX_REPS = PosixScaled(POSIX_SCALE, 3, 1)

# Time limits of the elbencho runs (RunPosixScenarios): a run with its own time limit gets that limit, a run that
# reads whole files the time its client needs at POSIX_MIN_READ_MIB_PER_S, and every run POSIX_RUN_SLACK_SECONDS on
# top for starting and stopping elbencho. In a full run the hot runs took 60 to 63 s, the cold reps 24 to 44 s, a
# client's concurrent read 7 to 19 s, a re-read at most 29 s and the warm-up at most 149 s, about 330 MiB/s per
# client. A run that has not ended within its limit is hung, and its step fails within minutes.
POSIX_RUN_SLACK_SECONDS = 300
POSIX_MIN_READ_MIB_PER_S = 100
PosixReadLimit = lambda bytes: int -> int {
    bytes // (POSIX_MIN_READ_MIB_PER_S * 1048576) + POSIX_RUN_SLACK_SECONDS
}

# Every AzCli step signs in once, and kubectl reuses that Entra ID login; a workload identity login in a pipeline
# task can fail after about an hour. The long steps of this pipeline (the data set, the two parts of each side,
# enabling DACS and the summary) therefore stop at this limit, so a stalled step fails with its own error rather
# than with an expired sign-in. The longest of them took 37 minutes in a full run.
POSIX_STEP_TIMEOUT_MINUTES = 55

# bf2BlockMiB is the BlobFuse2 block size, chosen per scenario so BlobFuse2 and DACS run at their best:
# 1 MiB for small blocks and thread scaling, and 4 MiB for the 4 MiB random reads. The re-read scenario
# mounts BlobFuse2 with its default block size, which is 0 here.
schema PosixScenario:
    id: str
    group: "hot" | "cold" | "concurrent" | "reread"
    blockSize: str
    threads: int
    bf2BlockMiB: int
    sides: ["bf2" | "dacs" | "alluxio"]

    check:
        threads > 0, "threads must be positive"
        (group == "reread") == (bf2BlockMiB == 0), "bf2BlockMiB must be 0 exactly for the re-read scenario"

# Execution order. blockSize is elbencho's -b.
# The ids number benchmark cases after those of the S3 read pipeline (1 to 12 there). A range is one elbencho run
# that covers several cases (13-16: hot random reads in 4 KiB and 64 KiB blocks; 21-22 and 23-24: the cold and
# concurrent reads); 17 and 18 are hot random reads in 1 MiB and 4 MiB blocks, and 19 and 20 thread scaling. A
# suffix tells apart the runs of one id (a/b, t<threads>), for example one run per thread count.
# Cases 25 to 28 are sequential reads, which this pipeline does not run. The ids appear in the result labels and in
# summary.json.
POSIX_SCENARIOS: [PosixScenario] = [
    PosixScenario {id = "13-16a", group = "hot", blockSize = "4K", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "13-16b", group = "hot", blockSize = "64K", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "17", group = "hot", blockSize = "1M", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "18-t8", group = "hot", blockSize = "4M", threads = 8, bf2BlockMiB = 4, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "18-t32", group = "hot", blockSize = "4M", threads = 32, bf2BlockMiB = 4, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "19-t1", group = "hot", blockSize = "64K", threads = 1, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "19-t4", group = "hot", blockSize = "64K", threads = 4, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "20-t16", group = "hot", blockSize = "64K", threads = 16, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "20-t64", group = "hot", blockSize = "64K", threads = 64, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "21-22", group = "cold", blockSize = "64K", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "23-24", group = "concurrent", blockSize = "16M", threads = 8, bf2BlockMiB = 1, sides = ["bf2", "dacs", "alluxio"]}
    PosixScenario {id = "29", group = "reread", blockSize = "16M", threads = 1, bf2BlockMiB = 0, sides = ["bf2", "alluxio"]}
]

# The sides of the cold, concurrent-read and re-read scenarios, as JSON for checks.jq posix_dataset: each of these
# sides reads its own files of those scenarios, so no side reads a blob another side has read before it.
POSIX_DATASET_SIDES = json.encode({scenario.group: sorted(scenario.sides) for scenario in POSIX_SCENARIOS if scenario.group != "hot"})

# The label that selects the elbencho service pods.
POSIX_CLIENT_LABEL = "app=posix-client"

# Image of the privileged pod that drops a node's page cache. It only needs a shell.
POSIX_DROP_CACHE_IMAGE = "mcr.microsoft.com/azurelinux/base/core:3.0"

# ShellSetup plus this pipeline's failure marker for fail() and the ERR trap. POSIX_WORK and POSIX_RESULT
# are the scratch and result directories for the functions in POSIX_RUNTIME_SHELL; POSIX_NS is the namespace
# of the elbencho service pods and of the Alluxio cluster.
PosixShellSetup = lambda workDir: str, resultDir: str -> str {
    ShellSetup(workDir, resultDir) + """
POSIX_WORK="${workDir}"
POSIX_RESULT="${resultDir}"
POSIX_NS="alx-ns"
fail() {
    echo "ALLUXIO POSIX READ FAILED: $*" >&2
    exit 1
}
trap 'echo "ALLUXIO POSIX READ FAILED: command at line $LINENO exited with status $?" >&2' ERR
"""
}

# How long pod_run goes on polling while no poll can read the status of a run: long enough to ride out a short
# outage of the API server or of the sign-in, and far below every run's limit and the step limit.
POSIX_POLL_LOST_SECONDS = 300

# Shell functions shared by the POSIX benchmark steps. They expect PosixShellSetup before them.
POSIX_RUNTIME_SHELL = """
# Runs a script in a pod, detached. A kubectl exec stream can drop during a long run and still return 0
# while the work keeps going in the pod. So one short exec writes the script, sets its status file to
# "pending" and starts it with setsid, stdio not tied to the exec, and later short execs poll the status
# file until it holds the exit status. The starter script also records the pod's own clock right before
# and after the script, and the process group id so a run can be killed. Every short exec is cut off after
# 60 s, so a stalled stream cannot hang the step. A poll whose exec fails or is cut off is tried again, but
# when no poll has read the status for POSIX_POLL_LOST_SECONDS, the pod is gone or kubectl can no longer reach
# it, for example because the step's sign-in has lapsed: the run then fails with the last error. A run whose
# status is still "pending" at its limit fails too, and the message tells whether the script was still running
# or had stopped without writing its status. In both cases its process group is killed, if the pod can still
# be reached. After a successful run the log and the two times are fetched again and again until they
# arrive, never from a failed exec's error text. The log goes to stdout (or to stderr when the script
# fails), through redact when the step defines it, as do the poll errors; POSIX_RUN_START and POSIX_RUN_END
# hold the pod-side UTC times.
# Usage: pod_run <pod> <limit seconds> <script text> [args...]
pod_run() {
    local pod="$1" limit="$2" script="$3" rc="" deadline last_ok log state=""
    shift 3
    [[ "$limit" =~ ^[0-9]+$ ]] || fail "pod_run: the limit must be a number of seconds, got $limit"
    timeout 60 kubectl exec -n "$POSIX_NS" "$pod" -- sh -c 'printf "%s\\n" "$1" > /tmp/posix-run.sh
        printf "%s\\n" "$2" > /tmp/posix-start.sh
        shift 2
        rm -f /tmp/posix-run.rc /tmp/posix-run.log /tmp/posix-run.start /tmp/posix-run.end /tmp/posix-run.pid
        echo pending > /tmp/posix-run.rc
        setsid sh /tmp/posix-start.sh "$@" < /dev/null > /dev/null 2>&1 &
        echo $! > /tmp/posix-run.pid' sh "$script" 'date -u +%Y-%m-%dT%H:%M:%SZ > /tmp/posix-run.start
sh /tmp/posix-run.sh "$@" > /tmp/posix-run.log 2>&1
status=$?
date -u +%Y-%m-%dT%H:%M:%SZ > /tmp/posix-run.end
echo $status > /tmp/posix-run.rc' "$@" || fail "$pod: could not start the script"
    deadline=$((SECONDS + limit))
    last_ok=$SECONDS
    # Poll every 15 s: often enough to notice the end of a short run, rarely enough not to load the API
    # server during a long one. "pending" is a run that is still going, and an empty file a status that is
    # still being written.
    while :; do
        if rc="$(timeout 60 kubectl exec -n "$POSIX_NS" "$pod" -- cat /tmp/posix-run.rc 2> "$POSIX_WORK/poll-$pod.err")"; then
            last_ok=$SECONDS
            [[ "$rc" =~ ^[0-9]+$ ]] && break
        else
            # timeout exits with 124 when it cuts the exec off.
            if (( $? == 124 )); then
                echo "kubectl exec did not return within 60 s" >> "$POSIX_WORK/poll-$pod.err"
            fi
            if (( SECONDS - last_ok >= ${POSIX_POLL_LOST_SECONDS} )); then
                rc=unreachable
                break
            fi
        fi
        if (( SECONDS >= deadline )); then
            rc=timeout
            break
        fi
        sleep 15
    done
    if [[ "$rc" != 0 ]]; then
        if [[ "$rc" == timeout || "$rc" == unreachable ]]; then
            # The negative pid is the process group started by setsid. The exec prints whether the group was
            # still there, and nothing if the pod cannot be reached.
            state="$(timeout 60 kubectl exec -n "$POSIX_NS" "$pod" -- sh -c 'pid="$(cat /tmp/posix-run.pid)"
                if kill -0 -"$pid" 2> /dev/null; then kill -- -"$pid"; echo running; else echo gone; fi' 2> /dev/null)" || true
        fi
        if [[ "$rc" == unreachable ]]; then
            fail "$pod: no check could read the status of the run for $((SECONDS - last_ok)) s; the last one failed with: $(redact_log < "$POSIX_WORK/poll-$pod.err" | tail -n 5)"
        fi
        { timeout 60 kubectl exec -n "$POSIX_NS" "$pod" -- cat /tmp/posix-run.log 2>&1 || true; } | redact_log >&2
        if [[ "$rc" == timeout ]]; then
            case "$state" in
                running) fail "$pod: the script was still running at its limit of $limit s" ;;
                gone) fail "$pod: the script was no longer running at its limit of $limit s but had not written its exit status" ;;
                *) fail "$pod: the script had not written its exit status by its limit of $limit s" ;;
            esac
        fi
        fail "$pod: script ended with exit status $rc"
    fi
    log="$(pod_cat "$pod" /tmp/posix-run.log)"
    POSIX_RUN_START="$(pod_cat "$pod" /tmp/posix-run.start)"
    POSIX_RUN_END="$(pod_cat "$pod" /tmp/posix-run.end)"
    [[ "$POSIX_RUN_START" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ && "$POSIX_RUN_END" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] ||
        fail "$pod: the pod-side times are not UTC timestamps: $POSIX_RUN_START $POSIX_RUN_END"
    redact_log <<< "$log"
}

# Copies stdin to stdout through the step's redact function, if it has one.
redact_log() {
    if declare -F redact > /dev/null; then redact; else cat; fi
}

# Prints one file of a pod. A failed exec prints an error text instead of the file, so only the output
# of a successful one counts; a few attempts cover a dropped stream.
# Usage: pod_cat <pod> <file>
pod_cat() {
    local out attempt
    for attempt in 1 2 3 4 5; do
        if out="$(timeout 60 kubectl exec -n "$POSIX_NS" "$1" -- cat "$2" 2> /dev/null)"; then
            printf '%s\\n' "$out"
            return 0
        fi
        sleep 5
    done
    fail "$1: could not fetch $2"
}

# Prints "<name><TAB><address>" for each Ready elbencho service pod, sorted by name, from one listing,
# and fails unless there are exactly ${POSIX_CLIENT_COUNT}: a missing service would silently shrink the
# load. client_pods and client_ips print one column of it.
client_list() {
    local pods list count
    pods="$(kubectl get pods -n "$POSIX_NS" -l ${POSIX_CLIENT_LABEL} -o json)" ||
        fail "could not list the elbencho service pods"
    list="$(jq -r '[.items | sort_by(.metadata.name)[] |
        select(.status.phase == "Running" and
            any(.status.conditions[]?; .type == "Ready" and .status == "True")) |
        [.metadata.name, .status.podIP] | select(.[1] != null and .[1] != "")] | .[] | @tsv' <<< "$pods")"
    count="$(grep -c . <<< "$list" || true)"
    [[ "$count" == ${POSIX_CLIENT_COUNT} ]] ||
        fail "expected ${POSIX_CLIENT_COUNT} ready elbencho service pods, found $count"
    echo "$list"
}
client_pods() {
    client_list | cut -f1
}
client_ips() {
    client_list | cut -f2
}

POSIX_MASTER_SCRIPT='hosts="$1"
shift
elbencho --hosts "$hosts" --nolive "$@"'
POSIX_LOCAL_SCRIPT='elbencho "$@"'

# A result file must hold elbencho's result table, whose header line starts with OPERATION.
eb_check_result() {
    grep -q OPERATION "$1" || fail "$2: no elbencho result table in $1"
}

# Index lines carry the group of the run ("group") when POSIX_GROUP is set, so the summary can tell the
# single runs of the hot group from the one entry that spans them all.
POSIX_GROUP="\${POSIX_GROUP:-}"
# The jq object that is appended to the index file; a rep is a number, or a word such as "all" for an
# entry that spans several runs. label and end are jq keywords: jq 1.6 accepts them only as quoted keys and
# not as variable names, hence $name and $finish.
POSIX_INDEX_LINE='{"label": $name, side: $side, scenario: $scenario, rep: ($rep | if test("^[0-9]+$") then tonumber else . end), start: $start, "end": $finish}
    + (if $pod == "" then {} else {pod: $pod} end) + (if $group == "" then {} else {group: $group} end)'

# Runs elbencho from the first service pod against all of them and records the result. The index line
# lets the summary find the run and place it in time for the counter and egress windows; its times are
# the pod's own, taken right around the elbencho command. limit is the run's pod_run limit.
# Usage: eb_run <label> <side> <scenario> <rep> <limit seconds> <elbencho args...>
eb_run() {
    local label="$1" side="$2" scenario="$3" rep="$4" limit="$5" list first hosts
    shift 5
    list="$(client_list)"
    first="$(head -n 1 <<< "$list" | cut -f1)"
    hosts="$(cut -f2 <<< "$list" | paste -sd, -)"
    [[ -n "$first" && -n "$hosts" ]] || fail "eb_run $label: no service pods"
    pod_run "$first" "$limit" "$POSIX_MASTER_SCRIPT" "$hosts" "$@" > "$POSIX_RESULT/$label.txt"
    eb_check_result "$POSIX_RESULT/$label.txt" "eb_run $label"
    jq -nc --arg name "$label" --arg side "$side" --arg scenario "$scenario" --arg rep "$rep" \\
        --arg start "$POSIX_RUN_START" --arg finish "$POSIX_RUN_END" --arg pod "" --arg group "$POSIX_GROUP" \\
        "$POSIX_INDEX_LINE" >> "$POSIX_RESULT/index.jsonl"
}

# Runs elbencho in one service pod against its own mount only and records it like eb_run, with the pod
# name in "pod" (the re-read scenario: the same node reads the file twice).
# Usage: eb_local <label> <side> <scenario> <rep> <pod> <limit seconds> <elbencho args...>
eb_local() {
    local label="$1" side="$2" scenario="$3" rep="$4" pod="$5" limit="$6"
    shift 6
    pod_run "$pod" "$limit" "$POSIX_LOCAL_SCRIPT" "$@" > "$POSIX_RESULT/$label.txt"
    eb_check_result "$POSIX_RESULT/$label.txt" "eb_local $label"
    jq -nc --arg name "$label" --arg side "$side" --arg scenario "$scenario" --arg rep "$rep" \\
        --arg start "$POSIX_RUN_START" --arg finish "$POSIX_RUN_END" --arg pod "$pod" --arg group "$POSIX_GROUP" \\
        "$POSIX_INDEX_LINE" >> "$POSIX_RESULT/index.jsonl"
}

# Runs the same local elbencho command in every service pod at the same time (the concurrent-readers
# scenario) and stores one result and one index line per pod, with the pod name in "pod". The scenario
# is always 23-24. path is the file all pods read; limit is the pod_run limit of each pod's run.
# Usage: eb_local_all <label> <side> <rep> <limit seconds> <path> <elbencho args...>
eb_local_all() {
    local label="$1" side="$2" rep="$3" limit="$4" path="$5" pod pids=() failed=0 pods
    shift 5
    pods="$(client_pods)"
    for pod in $pods; do
        (
            pod_run "$pod" "$limit" "$POSIX_LOCAL_SCRIPT" "$@" "$path" > "$POSIX_RESULT/$label-$pod.txt"
            eb_check_result "$POSIX_RESULT/$label-$pod.txt" "eb_local_all $label ($pod)"
            jq -nc --arg name "$label-$pod" --arg side "$side" --arg scenario 23-24 --arg rep "$rep" \\
                --arg start "$POSIX_RUN_START" --arg finish "$POSIX_RUN_END" --arg pod "$pod" --arg group "$POSIX_GROUP" \\
                "$POSIX_INDEX_LINE" > "$POSIX_WORK/index-$label-$pod.json"
        ) &
        pids+=($!)
    done
    for pid in "\\${pids[@]}"; do
        wait "$pid" || failed=1
    done
    (( failed == 0 )) || fail "eb_local_all $label: a pod failed"
    for pod in $pods; do
        cat "$POSIX_WORK/index-$label-$pod.json" >> "$POSIX_RESULT/index.jsonl"
    done
}

# The metrics text of every pod of one kind, each preceded by a comment line with the pod name. A pod
# listing that fails is an error. No pods at all means the kind is not deployed in this phase; any other
# number than ${POSIX_CACHE_COUNT} means a pod is missing or restarting.
# Usage: metrics_of <namespace> <pod name prefix> <port> <path>
metrics_of() {
    local list pods pod count
    list="$(kubectl get pods -n "$1" -o name)" || fail "could not list the pods in $1"
    pods="$(sed 's|^pod/||' <<< "$list" | grep "^$2" || true)"
    count="$(grep -c . <<< "$pods" || true)"
    [[ "$count" == 0 || "$count" == ${POSIX_CACHE_COUNT} ]] ||
        fail "expected ${POSIX_CACHE_COUNT} $2 pods in $1, found $count"
    for pod in $pods; do
        echo "# pod $pod"
        kubectl get --raw "/api/v1/namespaces/$1/pods/$pod:$3/proxy/$4" || fail "could not read the metrics of $1/$pod"
    done
}
# 30000 is the Alluxio worker metrics port and 9096 the DACS server's.
alluxio_metrics() {
    metrics_of "$POSIX_NS" alluxio-worker- 30000 metrics/
}
dacs_metrics() {
    metrics_of dacs-cache-system bench-cache- 9096 metrics
}
count_pods() {
    grep -c '^# pod ' <<< "$1" || true
}

# Saves the raw metrics of all Alluxio workers and all DACS servers to counters-<tag>.prom, whose first
# line records how many pods of each kind were read. A kind that is not deployed in this phase
# contributes nothing.
# Usage: snap_counters <tag>
snap_counters() {
    local alluxio dacs
    alluxio="$(alluxio_metrics)" || fail "could not read the Alluxio worker metrics"
    dacs="$(dacs_metrics)" || fail "could not read the DACS server metrics"
    {
        echo "# pods alluxio-worker-=$(count_pods "$alluxio") bench-cache-=$(count_pods "$dacs")"
        echo "$alluxio"
        echo "$dacs"
    } > "$POSIX_RESULT/counters-$1.prom"
}

# Runs a privileged pod on one node that flushes and drops the page cache, so the next read has to
# come from the cache layer rather than from the node's memory.
# Usage: drop_page_cache <node>
drop_page_cache() {
    local node="$1" name="drop-cache-$1"
    kubectl delete pod "$name" -n "$POSIX_NS" --ignore-not-found > /dev/null
    kubectl create -n "$POSIX_NS" -f - << MANIFEST || fail "could not create $name"
apiVersion: v1
kind: Pod
metadata:
  name: $name
spec:
  nodeName: $node
  restartPolicy: Never
  tolerations:
    - operator: Exists
  containers:
    - name: drop
      image: ${POSIX_DROP_CACHE_IMAGE}
      securityContext:
        privileged: true
      command: ["sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches"]
MANIFEST
    # 180 s covers pulling the image on a fresh node and running two commands.
    kubectl wait -n "$POSIX_NS" --for=jsonpath='{.status.phase}'=Succeeded "pod/$name" --timeout=180s ||
        { kubectl delete pod "$name" -n "$POSIX_NS" --ignore-not-found > /dev/null; fail "dropping the page cache on $node failed"; }
    kubectl delete pod "$name" -n "$POSIX_NS" --ignore-not-found > /dev/null
}

# The DACS servers' successful Upload requests, summed. Uploads are the asynchronous writes of freshly
# generated data to the cache. Every one of the ${POSIX_CACHE_COUNT} servers must be read and must report the
# metric: a missing server or metric would look like "no uploads" and end the wait too early.
dacs_uploads() {
    local out total servers seen
    out="$(dacs_metrics)" || fail "could not read the DACS server metrics"
    read -r total servers seen < <(awk '
        /^# pod / { pods++; next }
        /^cache_server_request_counter[{]/ && /request_type="Upload"/ && /status="Success"/ {
            sum += $NF
            if (!(pods in has)) { has[pods] = 1; seen_n++ }
        }
        END { printf "%d %d %d\\n", sum, pods, seen_n }' <<< "$out")
    [[ "$servers" == ${POSIX_CACHE_COUNT} ]] || fail "expected ${POSIX_CACHE_COUNT} DACS servers, found $servers"
    [[ "$seen" == "$servers" ]] || fail "$((servers - seen)) of $servers DACS servers report no Upload request metric"
    echo "$total"
}

# Waits until the DACS Upload counter has not moved for two checks 20 seconds apart. Gives up after 10
# minutes, because a cache that is still absorbing data would distort the next measurement.
dacs_settle() {
    local previous current stable=0 deadline=$((SECONDS + 600))
    previous="$(dacs_uploads)"
    while (( stable < 2 )); do
        (( SECONDS < deadline )) || fail "DACS uploads still changing after 10 minutes"
        sleep 20
        current="$(dacs_uploads)"
        if [[ "$current" == "$previous" ]]; then
            stable=$((stable + 1))
        else
            stable=0
        fi
        previous="$current"
    done
}

# Waits until every elbencho service pod lists exactly ${POSIX_HOT_FILES} hot files (p*) in /data, for up to
# 300 s. The Blob CSI driver mounts BlobFuse2 with --cancel-list-on-mount-seconds=10, so a listing in the
# first 10 s after a mount is empty: the first check waits 15 s. The pod list is an assignment, so a missing or
# NotReady pod fails here instead of leaving the loop with no pod checked.
wait_hot_listing() {
    local deadline pods pod listing seen behind
    sleep 15
    deadline=$((SECONDS + 300))
    while :; do
        behind=0
        pods="$(client_pods)"
        for pod in $pods; do
            if listing="$(timeout 60 kubectl exec -n "$POSIX_NS" "$pod" -- ls -1 /data 2> /dev/null)"; then
                seen="$(grep -c '^p' <<< "$listing" || true)"
            else
                seen=unreadable
            fi
            if [[ "$seen" != ${POSIX_HOT_FILES} ]]; then
                behind=1
                echo "$pod lists $seen hot files, expecting ${POSIX_HOT_FILES}"
            fi
        done
        (( behind == 0 )) && return 0
        (( SECONDS < deadline )) || fail "not every client lists ${POSIX_HOT_FILES} hot files after 300 seconds"
        sleep 10
    done
}

# Replaces the Blob volume and the elbencho service pods: deletes the pods, the PVC and the PV posix-data
# (waiting until they are gone), creates them again from blob-volume.yaml and clients-volume.yaml in the
# manifest directory with the given BlobFuse2 mount options, and waits for exactly ${POSIX_CLIENT_COUNT} Ready
# pods that list the hot files. The Secret posix-sas (read-only SAS) stays in place. options is a JSON list
# with one option per item: the Blob CSI driver recognizes some options only as separate items.
# Every mount gets a new volumeHandle, which names the node's staging mount, so a node cannot keep a staging
# mount of the previous volume with the previous options.
# Usage: mount_posix_volume <manifest dir> <container> <elbencho image> <tag> <options as a JSON list>
mount_posix_volume() {
    local dir="$1" container="$2" image="$3" tag="$4" options="$5" handle index left
    handle="posix-data-$tag-$(date -u +%Y%m%d%H%M%S)"
    # 300 s bounds each deletion: a pod waits for its BlobFuse2 unmount, the PVC and PV for their finalizers.
    kubectl delete pod -n "$POSIX_NS" -l ${POSIX_CLIENT_LABEL} --ignore-not-found --wait=true --timeout=300s > /dev/null ||
        fail "could not delete the elbencho service pods within 300 s"
    kubectl delete pvc posix-data -n "$POSIX_NS" --ignore-not-found --wait=true --timeout=300s > /dev/null ||
        fail "could not delete the PVC posix-data within 300 s"
    kubectl delete pv posix-data --ignore-not-found --wait=true --timeout=300s > /dev/null ||
        fail "could not delete the PV posix-data within 300 s"
    left="$(kubectl get pods -n "$POSIX_NS" -l ${POSIX_CLIENT_LABEL} -o name)" || fail "could not list the elbencho service pods"
    [[ -z "$left" ]] || fail "elbencho service pods still exist after their deletion: $left"
    ! kubectl get pv posix-data > /dev/null 2>&1 || fail "the PV posix-data still exists after its deletion"
    sed -e "s|CONTAINER_NAME|$container|" \\
        -e "s|volumeHandle: posix-data|volumeHandle: $handle|" \\
        -e "s|mountOptions: \\[\\]|mountOptions: $options|" \\
        "$dir/blob-volume.yaml" > "$POSIX_WORK/volume-$tag.yaml"
    grep -qF "mountOptions: $options" "$POSIX_WORK/volume-$tag.yaml" || fail "blob-volume.yaml has no empty mountOptions to fill"
    kubectl create -f "$POSIX_WORK/volume-$tag.yaml" > /dev/null
    for index in $(seq 1 ${POSIX_CLIENT_COUNT}); do
        sed -e "s|ELBENCHO_IMAGE|$image|" -e "s|name: posix-client|name: posix-client-$index|" \\
            "$dir/clients-volume.yaml" > "$POSIX_WORK/client-$index.yaml"
        kubectl create -f "$POSIX_WORK/client-$index.yaml" > /dev/null
    done
    kubectl wait -n "$POSIX_NS" --for=condition=Ready pod -l ${POSIX_CLIENT_LABEL} --timeout=600s > /dev/null
    wait_hot_listing
}
"""

# Creates the storage account and container, writes the benchmark data into it and verifies it: one hot pool
# that every system under test reads, and for each side its own cold, concurrent-read and re-read files of the
# same sizes (checks.jq posix_dataset), so no side reads a blob that another side has read before.
#
# The account is created and the SAS tokens are made the way the S3 pipeline does it (BLOB_SAS_SHELL,
# StorageAccountFunctionStart). The read SAS (8 hours, longer than the 360-minute job) is published as the
# secret pipeline variable POSIX_READ_SAS for the later steps. The write SAS lasts 4 hours, longer than this step
# can run (POSIX_STEP_TIMEOUT_MINUTES), and never leaves this step: it is only in the shell and in a Secret that
# is deleted with the read-write volume.
#
# Order, which matters for the BlobFuse2 negative-lookup cache (it hides a new file on other nodes for 120 s):
#   0. Whatever an earlier attempt of this step left in the cluster is deleted, so a retry starts clean; an
#      existing account and container are reused, and the files of an earlier attempt are overwritten.
#   1. The read-only volume and the elbencho service pods mount the container, still empty on a first attempt.
#   2. One pod mounts the container read-write (a BlobFuse2 block cache) and writes the files with elbencho,
#      in 8 lanes of one file at a time.
#   3. The read-write volume is deleted, which flushes and unmounts it.
#   4. `az storage blob list` must show exactly the planned files, all flat, with no directory marker.
#   5. Every service pod must list all POSIX_HOT_FILES hot files through its own mount, for up to 300 s.
# The read-only Secret posix-sas, the PV and PVC posix-data and the pods posix-client-<n> are left in place
# for the following steps, which must delete them before they mount the volume with other options.
# Needs the cluster, the namespace and the node pools to exist.
GeneratePosixDatasets = lambda subscription: str, resourceGroup: str, location: str, account: str, container: str, elbenchoImage: str, workDir: str, resultDir: str, checksDir: str, serviceConnection: str = const.DEFAULT_SERVICE_CONNECTION -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Create the Blob data set for the POSIX reads"
        PosixShellSetup(workDir, resultDir) + SecretCommands(workDir) + BLOB_SAS_SHELL + """
redact() {
    local line secret
    while IFS= read -r line || [[ -n "$line" ]]; do
        for secret in "\${read_sas:-}" "\${write_sas:-}"; do
            if [[ -n "$secret" ]]; then line="\${line//"$secret"/<redacted>}"; fi
        done
        printf '%s\\n' "$line"
    done
}
""" + POSIX_RUNTIME_SHELL + StorageAccountFunctionStart("create_account", "", resourceGroup, subscription) + """}

# Renders a manifest of the checks directory into the work directory with the given sed expressions and
# creates it. A manifest is created, never applied, so no secret or annotation is stored with it.
# Usage: create_manifest <manifest file name> <output name> <sed expression>...
create_manifest() {
    local source="$1" output="$POSIX_WORK/$2"
    shift 2
    sed "$@" "${checksDir}/$source" > "$output"
    kubectl create -f "$output" > /dev/null
}

# 0. A retry starts clean. A failed attempt leaves the writer pod, the client pods, their volumes and the Secrets
# behind, and creating them again would fail. Pods go first (each waits for its BlobFuse2 unmount), then the
# PVCs and PVs (their finalizers), then the Secrets; 300 s bounds each deletion.
kubectl delete pod posix-gen-1 -n "$POSIX_NS" --ignore-not-found --wait=true --timeout=300s > /dev/null ||
    fail "could not delete the leftover writer pod posix-gen-1 within 300 s"
kubectl delete pod -n "$POSIX_NS" -l ${POSIX_CLIENT_LABEL} --ignore-not-found --wait=true --timeout=300s > /dev/null ||
    fail "could not delete the leftover elbencho service pods within 300 s"
for name in posix-gen posix-data; do
    kubectl delete pvc "$name" -n "$POSIX_NS" --ignore-not-found --wait=true --timeout=300s > /dev/null ||
        fail "could not delete the leftover PVC $name within 300 s"
done
for name in posix-gen posix-data; do
    kubectl delete pv "$name" --ignore-not-found --wait=true --timeout=300s > /dev/null ||
        fail "could not delete the leftover PV $name within 300 s"
done
for name in posix-gen-sas posix-sas; do
    kubectl delete secret "$name" -n "$POSIX_NS" --ignore-not-found --wait=true --timeout=300s > /dev/null ||
        fail "could not delete the leftover Secret $name within 300 s"
done
# Every volume gets a new volumeHandle, which names the node's staging mount, so a node cannot keep a staging
# mount of an earlier attempt (with that attempt's SAS).
handle_stamp="$(date -u +%Y%m%d%H%M%S)"

# On an account and container that exist from an earlier attempt, both commands succeed without a change:
# account create updates the account in place with the same settings, container create reports
# {"created": false}.
create_account "${account}" "${location}"
az storage container create \\
    --name "${container}" \\
    --public-access off > /dev/null
read_sas="$(make_sas "${container}" rl 8)" || fail "Could not generate the read SAS; secret-bearing output withheld"
# racwl: elbencho creates, writes and reads back files through BlobFuse2, which also lists the container.
write_sas="$(make_sas "${container}" racwl 4)" || fail "Could not generate the write SAS; secret-bearing output withheld"

# 1. Read-only volume and the elbencho service pods, mounted before any data exists.
kubectl create secret generic posix-sas -n "$POSIX_NS" \\
    --from-literal=azurestorageaccountname="${account}" \\
    --from-file=azurestorageaccountsastoken=<(printf '%s' "$read_sas") \\
    > /dev/null 2> >(redact >&2)
create_manifest blob-volume.yaml volume-ro.yaml \\
    -e "s|CONTAINER_NAME|${container}|" \\
    -e "s|volumeHandle: posix-data|volumeHandle: posix-data-gen-$handle_stamp|" \\
    -e 's|mountOptions: \\[\\]|mountOptions: ["--read-only=true", "--allow-other=true"]|'
for index in $(seq 1 ${POSIX_CLIENT_COUNT}); do
    create_manifest clients-volume.yaml "client-$index.yaml" \\
        -e "s|ELBENCHO_IMAGE|${elbenchoImage}|" \\
        -e "s|name: posix-client|name: posix-client-$index|"
done
kubectl wait -n "$POSIX_NS" --for=condition=Ready pod -l ${POSIX_CLIENT_LABEL} --timeout=600s

# 2. The writer: the same volume and pod templates, renamed, read-write, with a BlobFuse2 block cache of
# 16 MiB blocks. Its label differs from the clients', so it is not one of the elbencho hosts.
# The write Secret must not outlive a failed step. This replaces the setup's EXIT trap with its cleanup plus the
# Secret's deletion.
trap '${ShellCleanup(workDir)}; kubectl delete secret posix-gen-sas -n "$POSIX_NS" --ignore-not-found > /dev/null 2>&1 || true' EXIT
kubectl create secret generic posix-gen-sas -n "$POSIX_NS" \\
    --from-literal=azurestorageaccountname="${account}" \\
    --from-file=azurestorageaccountsastoken=<(printf '%s' "$write_sas") \\
    > /dev/null 2> >(redact >&2)
create_manifest blob-volume.yaml volume-rw.yaml \\
    -e 's|posix-data|posix-gen|g' \\
    -e 's|posix-sas|posix-gen-sas|g' \\
    -e 's|ReadOnlyMany|ReadWriteMany|g' \\
    -e 's|readOnly: true|readOnly: false|g' \\
    -e "s|volumeHandle: posix-gen|volumeHandle: posix-gen-$handle_stamp|" \\
    -e "s|CONTAINER_NAME|${container}|" \\
    -e 's|mountOptions: \\[\\]|mountOptions: ["--allow-other=true", "--block-cache", "--block-cache-block-size=16"]|'
create_manifest clients-volume.yaml writer.yaml \\
    -e "s|ELBENCHO_IMAGE|${elbenchoImage}|" \\
    -e 's|name: posix-client|name: posix-gen-1|' \\
    -e 's|app: posix-client|app: posix-gen|g' \\
    -e 's|posix-data|posix-gen|g' \\
    -e 's|readOnly: true|readOnly: false|g'
kubectl wait -n "$POSIX_NS" --for=condition=Ready pod/posix-gen-1 --timeout=600s
# The planned files, name and size; checks.jq is the one owner of the plan for the writer and the verification.
jq -n -L "${checksDir}" -L "${checksDir}/.." --argjson sides '${POSIX_DATASET_SIDES}' \\
    'include "checks"; posix_dataset(${POSIX_HOT_FILES}; ${POSIX_HOT_FILE_MIB}; ${POSIX_COLD_FILES}; ${POSIX_CC_FILES}; ${POSIX_BIG_FILE_GIB}; ${POSIX_REREAD_GIB}; $sides)' > "$POSIX_WORK/dataset-plan.json"
# The writer keeps at most 8 files open: 8 lanes, each writing one file at a time with its own elbencho run of
# one thread over one explicit path (no -d, so no directory is created). elbencho shares every file of a run
# among all its threads, so one run over a whole size group held all of its files open at once, and BlobFuse2's
# block cache ran out of memory on their dirty blocks: the writes stalled with nothing committed. A lane's
# elbencho run ends with the file closed, which commits it to Blob, before the lane opens its next file.
# The lanes get the files largest first, each to the lane with the fewest bytes so far, so they end together.
# Lines: <lane>:<bytes>:<path>.
jq -r --argjson lanes 8 '([$lanes, length] | min) as $count
    | reduce sort_by(-.bytes, .name)[] as $file ({totals: [range(0; $count) | 0], lines: []};
        (.totals | index(min)) as $lane
        | .totals[$lane] += $file.bytes
        | .lines += ["\\($lane + 1):\\($file.bytes):/data/\\($file.name)"])
    | .lines[]' "$POSIX_WORK/dataset-plan.json" > "$POSIX_WORK/dataset-lanes.txt"
lanes="$(cut -d: -f1 "$POSIX_WORK/dataset-lanes.txt" | sort -u | wc -l | tr -d ' ')"
file_count="$(jq length "$POSIX_WORK/dataset-plan.json")"
[[ "$(wc -l < "$POSIX_WORK/dataset-lanes.txt" | tr -d ' ')" == "$file_count" && "$lanes" -ge 1 ]] ||
    fail "the writer's lane plan does not cover the $file_count planned files"
writes=()
while IFS= read -r line; do writes+=("$line"); done < "$POSIX_WORK/dataset-lanes.txt"
# The script in the writer pod (sh): starts the lanes, waits for all of them and prints each lane's log after
# a line "POSIX-WRITE-LANE <lane>". A lane stops at the first elbencho run that fails, and the other lanes stop
# after their current file, so the script fails closed without writing the rest.
# Usage: <lane count> <lane>:<bytes>:<path>...
POSIX_WRITE_SCRIPT='lanes="$1"
shift
dir=/tmp/posix-write
rm -rf "$dir"
mkdir -p "$dir"
lane=1
pids=""
while [ "$lane" -le "$lanes" ]; do
    (
        for entry in "$@"; do
            [ "\${entry%%:*}" = "$lane" ] || continue
            rest="\${entry#*:}"
            bytes="\${rest%%:*}"
            path="\${rest#*:}"
            if [ -e "$dir/failed" ]; then
                echo "lane $lane: stopped before $path because another lane failed"
                exit 1
            fi
            echo "lane $lane: writing $path, $bytes bytes"
            elbencho -w -t 1 -b 16M -s "$bytes" "$path"
            status=$?
            if [ "$status" -ne 0 ]; then
                touch "$dir/failed"
                echo "ALLUXIO POSIX READ FAILED: lane $lane: elbencho exited with status $status writing $path"
                exit 1
            fi
        done
    ) > "$dir/lane-$lane.log" 2>&1 &
    pids="$pids $!"
    lane=$((lane + 1))
done
failed=0
for pid in $pids; do
    wait "$pid" || failed=1
done
lane=1
while [ "$lane" -le "$lanes" ]; do
    echo "POSIX-WRITE-LANE $lane"
    cat "$dir/lane-$lane.log"
    lane=$((lane + 1))
done
exit $failed'
# One detached run for the whole data set: about 850 GiB at full scale, which a full run wrote in about 15 minutes
# (the whole step took 17). The 1800 s limit is twice that. The waits before and after the write add up to more
# than the rest of the hour in the worst case, so the step's own limit (POSIX_STEP_TIMEOUT_MINUTES) is what keeps
# its kubectl calls inside the Entra ID sign-in.
pod_run posix-gen-1 1800 "$POSIX_WRITE_SCRIPT" "$lanes" "\${writes[@]}" > "$POSIX_WORK/dataset-write.log"
# One result file per lane, dataset-write-<lane>.txt, with the result table of every file the lane wrote.
awk -v dir="$POSIX_RESULT" '/^POSIX-WRITE-LANE [0-9]+$/ { file = dir "/dataset-write-" $2 ".txt"; printf "" > file; next }
    file != "" { print > file }' "$POSIX_WORK/dataset-write.log"
for lane in $(seq 1 "$lanes"); do
    eb_check_result "$POSIX_RESULT/dataset-write-$lane.txt" "dataset write lane $lane"
done
tables="$(cat "$POSIX_RESULT"/dataset-write-*.txt | grep -c '^OPERATION' || true)"
[[ "$tables" == "$file_count" ]] || fail "the writer's lanes hold $tables elbencho result tables, expected one for each of the $file_count files"

# 3. Remove the writer. Deleting the pod waits for the unmount, which flushes BlobFuse2's cache to Blob; 300 s
# bounds each deletion.
kubectl delete pod posix-gen-1 -n "$POSIX_NS" --ignore-not-found --wait=true --timeout=300s > /dev/null ||
    fail "could not delete the writer pod posix-gen-1 within 300 s"
kubectl delete pvc posix-gen -n "$POSIX_NS" --ignore-not-found --wait=true --timeout=300s > /dev/null ||
    fail "could not delete the PVC posix-gen within 300 s"
kubectl delete pv posix-gen --ignore-not-found --wait=true --timeout=300s > /dev/null ||
    fail "could not delete the PV posix-gen within 300 s"
kubectl delete secret posix-gen-sas -n "$POSIX_NS" --ignore-not-found > /dev/null
unset write_sas

# 4. The container holds exactly the planned files. --include m exposes metadata.hdi_isfolder; --num-results
# is explicit so a truncated listing cannot pass.
az storage blob list \\
    --container-name "${container}" \\
    --include m \\
    --num-results 5000 |
    jq -e -L "${checksDir}" -L "${checksDir}/.." --argjson sides '${POSIX_DATASET_SIDES}' \\
        'include "checks"; validate_posix_dataset(${POSIX_HOT_FILES}; ${POSIX_HOT_FILE_MIB}; ${POSIX_COLD_FILES}; ${POSIX_CC_FILES}; ${POSIX_BIG_FILE_GIB}; ${POSIX_REREAD_GIB}; $sides)' > /dev/null ||
    fail "the Blob container does not hold exactly the planned data set"
unset AZURE_STORAGE_KEY

# 5. BlobFuse2 caches a failed lookup for 120 s, so a client that mounted the empty container may not see
# the new files yet. Wait, up to 300 s, until every client lists all the hot files.
deadline=$((SECONDS + 300))
while :; do
    behind=0
    # An assignment keeps a failure of client_pods (a missing or NotReady pod); a command substitution in the
    # for-list would swallow it and let the loop pass with no pod checked.
    pods="$(client_pods)"
    for pod in $pods; do
        if listing="$(timeout 60 kubectl exec -n "$POSIX_NS" "$pod" -- ls -1 /data 2> /dev/null)"; then
            seen="$(grep -c '^p' <<< "$listing" || true)"
        else
            seen=unreadable
        fi
        if [[ "$seen" != ${POSIX_HOT_FILES} ]]; then
            behind=1
            echo "$pod lists $seen hot files, expecting ${POSIX_HOT_FILES}"
        fi
    done
    (( behind == 0 )) && break
    (( SECONDS < deadline )) || fail "not every client lists ${POSIX_HOT_FILES} hot files after 300 seconds"
    sleep 10
done

publish_secret POSIX_READ_SAS "$read_sas"
unset read_sas
jq -n \\
    --arg account "${account}" --arg container "${container}" --arg location "${location}" \\
    --argjson sides '${POSIX_DATASET_SIDES}' \\
    '$ARGS.named + {hot_files: ${POSIX_HOT_FILES}, hot_file_mib: ${POSIX_HOT_FILE_MIB}, cold_files_per_pass: ${POSIX_COLD_FILES}, cc_files_per_pass: ${POSIX_CC_FILES}, big_file_gib: ${POSIX_BIG_FILE_GIB}, reread_file_gib: ${POSIX_REREAD_GIB}}' \\
    > "${resultDir}/dataset.json"
"""
        stepName = "posix_dataset"
        timeoutInMinutes = POSIX_STEP_TIMEOUT_MINUTES
    )
}

# The BlobFuse2 mount options of the Blob volume, one option per list item: the Blob CSI driver recognizes
# some options only as separate items (with the DACS discovery endpoint inside a combined item it adds a
# temporary path that BlobFuse2 then rejects).
# - "bf2" with blockMiB 0 is the Blob CSI default mount, kernel page cache on, for the re-read scenario.
# - "bf2" otherwise is BlobFuse2's block cache with the given block size, and the prefetch and parallelism of
#   Microsoft's published BlobFuse2 benchmark; the kernel cache is off so every read reaches BlobFuse2.
# - "dacs" reads through the DACS distributed cache, always in 1 MiB blocks. The discovery endpoint is the
#   Service of the Cache bench-cache (dacs-cache.yaml) in dacs-cache-system, on the Cache's port 9065. The
#   driver adds --distributed-cache-dns-server itself.
PosixMountOptions = lambda side: "bf2" | "dacs", blockMiB: int -> [str] {
    assert blockMiB >= 0, "blockMiB must not be negative, got ${blockMiB}"
    assert side == "bf2" or blockMiB == 1, "DACS reads in 1 MiB blocks, got ${blockMiB}"
    readOnly = ["--read-only=true", "--allow-other=true"]
    dacs = readOnly + ["--disable-kernel-cache=true", "--block-cache=false", "--streaming=false", "--preload=false", "--distributed-cache-discovery-endpoint=bench-cache-discovery.dacs-cache-system.svc.cluster.local:9065", "--distributed-cache-block-size=1", "--distributed-cache-prefetch=128", "--distributed-cache-parallelism=128"]
    blockCache = readOnly + ["--disable-kernel-cache=true", "--block-cache", "--block-cache-block-size=${blockMiB}", "--block-cache-prefetch=128", "--block-cache-parallelism=128"]
    dacs if side == "dacs" else (readOnly if blockMiB == 0 else blockCache)
}

# Shell snippet (it expects PosixShellSetup and POSIX_RUNTIME_SHELL before it) that replaces the Blob volume
# posix-data and the elbencho service pods with a mount of the given side and block size; see
# mount_posix_volume. checksDir holds blob-volume.yaml and clients-volume.yaml. The Secret posix-sas from
# GeneratePosixDatasets must exist.
MountPosixVolume = lambda side: "bf2" | "dacs", blockMiB: int, container: str, elbenchoImage: str, checksDir: str -> str {
    options = "[" + ", ".join(['"${option}"' for option in PosixMountOptions(side, blockMiB)]) + "]"
    "mount_posix_volume \"${checksDir}\" \"${container}\" \"${elbenchoImage}\" ${side}-${blockMiB} '${options}'\n"
}

# Each side runs as two steps: "hot" (warm-up and hot reads) and "rest" (cold, concurrent and re-read), so each
# step stays well within its Entra ID sign-in (POSIX_STEP_TIMEOUT_MINUTES). In a full run a side took 52 to 62
# minutes in one step; its warm-up and hot reads took 35 to 37 minutes and the rest 17 to 19.
POSIX_SIDE_PARTS: ["hot" | "rest"] = ["hot", "rest"]

# Runs the scenarios of POSIX_SCENARIOS that list this side, in table order, POSIX_REPS reps each. Part "hot" runs
# groups 1 and 2 and starts the side's runs file; part "rest" runs groups 3 to 5 after it, keeping the warm-up and
# hot results and dropping whatever an earlier attempt of the rest part left (see POSIX_SIDE_PARTS).
#   1. Cache sides (dacs, alluxio): one sequential read of the whole hot pool (the warm-up), after which the
#      cache must hold all of it within 120 s (Alluxio cached pages x 4 MiB, the worker default page size; DACS
#      Upload requests x 1 MiB) or the step fails. Alluxio first waits for exactly POSIX_CACHE_COUNT Ready
#      workers; DACS waits for its uploads to settle after the read. Then 120 s of quiet, so the warm-up's last
#      Blob metric minute stays out of the hot window.
#   2. Hot: the scenarios that share a BlobFuse2 block size run in a row, rep 1 of each, then rep 2, and so
#      on; BlobFuse2 is mounted again when the block size changes (1 MiB, 4 MiB for 18-t8/18-t32, 1 MiB). The
#      cache sides keep one mount but run in the same order. Each run reads random blocks of all hot files for
#      POSIX_REP_SECONDS. The cache sides prove the hot reads came from the cache with the counters before and
#      after the group (validate_cache_hits).
#   3. Cold: the bf2 and dacs sides first check that the volume still has the mount of the hot reads. Then 180 s
#      of quiet, and one rep per unread set <side>-cold-r<rep>, 70 s apart; DACS settles after each.
#   4. Concurrent: 70 s after the cold group, every client reads the whole set <side>-cc-r<rep> at the same time,
#      70 s between reps; counter snapshots around each rep on the cache sides; DACS settles after each.
#   5. Re-read (bf2, alluxio): BlobFuse2 is mounted with the CSI defaults; Alluxio FUSE is restarted with
#      direct I/O off (SetAlluxioDirectIo). After 70 s one client's node drops its page cache and the client
#      reads <side>-m8 twice, 70 s apart, with counter snapshots before, between and after on Alluxio.
# Every elbencho run has its own time limit (POSIX_RUN_SLACK_SECONDS) and every result is validated with
# validate_elbencho_run. Outputs in resultDir:
#   index.jsonl          appended: one line per run {label, side, scenario, rep, start, end, group, pod?}
#                        with pod-side UTC times; group is warmup, hot, cold, concurrent or reread. The warm-up
#                        is one entry {scenario: "warmup", rep: "all"}. After the hot group one more entry
#                        {scenario: "hot", rep: "all", group: "hot"} spans the first hot start to the last hot
#                        end. For Blob egress attribution take every line of the side except the single hot
#                        runs (group "hot" with a numeric rep).
#   runs-<side>.jsonl    one line per measured run (not the warm-up): its index line plus result, the
#                        parse_elbencho object.
#   counters-<side>-<tag>.prom  raw counter snapshots (cache sides): warmup-before/after, hot-before/after,
#                        23-24-r<rep>-before/after, and on Alluxio 29-before/between/after.
#   counters-<side>.jsonl     (cache sides) counter_delta of each concurrent rep, with side, scenario, rep.
#   warmup-<side>.json, hot-counters-<side>.json  (cache sides) the warm-up and hot-group counter proofs.
# The bf2 and dacs sides mount the Blob container through the Secret posix-sas and replace the pods that
# GeneratePosixDatasets left; the alluxio side uses the FUSE client pods of PrepareAlluxioFuseClients until its
# re-read restarts the FUSE pods and recreates them with elbenchoImage, so only container may be empty there.
# Nothing reads Blob after the last run, because the last group of a side owns the minutes after it in the
# egress attribution.
RunPosixScenarios = lambda side: "bf2" | "dacs" | "alluxio", container: str, elbenchoImage: str, workDir: str, resultDir: str, checksDir: str, part: "hot" | "rest", serviceConnection: str = const.DEFAULT_SERVICE_CONNECTION -> steps.Step {
    assert side == "alluxio" or container != "", "the ${side} side mounts the Blob volume and needs the container"
    assert elbenchoImage != "", "the ${side} side recreates the elbencho pods and needs the elbencho image"
    # The data set has one cold and one concurrent-read set per rep, three of each.
    assert POSIX_REPS <= 3, "the data set has three cold and three concurrent-read sets, got ${POSIX_REPS} reps"
    scenarios = [scenario for scenario in POSIX_SCENARIOS if side in scenario.sides]
    hot = [scenario for scenario in scenarios if scenario.group == "hot"]
    cold = [scenario for scenario in scenarios if scenario.group == "cold"]
    concurrent = [scenario for scenario in scenarios if scenario.group == "concurrent"]
    reread = [scenario for scenario in scenarios if scenario.group == "reread"]
    assert len(hot) > 0 and len(cold) == 1 and len(concurrent) == 1 and len(reread) <= 1, "each side runs hot scenarios, one cold, one concurrent and at most one re-read scenario"
    cache = side != "bf2"
    hotFileBytes = POSIX_HOT_FILE_MIB * 1048576
    hotBytes = POSIX_HOT_FILES * hotFileBytes
    bigFileBytes = POSIX_BIG_FILE_GIB * 1073741824
    # The cold reps' elbencho time limit, and the pod_run limit of each kind of run (see POSIX_RUN_SLACK_SECONDS). The
    # warm-up spreads the hot data set over all the clients; a concurrent rep reads a whole set on each client.
    coldSeconds = 120
    hotLimit = POSIX_REP_SECONDS + POSIX_RUN_SLACK_SECONDS
    coldLimit = coldSeconds + POSIX_RUN_SLACK_SECONDS
    warmLimit = PosixReadLimit(hotBytes // POSIX_CLIENT_COUNT)
    ccLimit = PosixReadLimit(POSIX_CC_FILES * bigFileBytes)
    rereadLimit = PosixReadLimit(POSIX_REREAD_GIB * 1073741824)
    # Runs of hot scenarios that share a BlobFuse2 block size: where each run starts and ends in hot.
    starts = [index for index in range(len(hot)) if index == 0 or hot[index].bf2BlockMiB != hot[index - 1].bf2BlockMiB]
    ends = starts[1:] + [len(hot)]
    # One run of scenarios: BlobFuse2's mount for their block size, then the reps, rotating over the scenarios.
    hotSegment = lambda segment: [PosixScenario] -> str {
        mount = MountPosixVolume("bf2", segment[0].bf2BlockMiB, container, elbenchoImage, checksDir) if side == "bf2" else ""
        runs = "".join(["    hot_run ${scenario.id} \"$rep\" ${scenario.blockSize} ${scenario.threads}\n" for scenario in segment])
        mount + "for rep in $(seq 1 ${POSIX_REPS}); do\n" + runs + "done\n"
    }
    hotShell = "".join([hotSegment(hot[starts[k]:ends[k]]) for k in range(len(starts))])
    dacsSettle = "    dacs_settle\n" if side == "dacs" else ""
    snap = lambda tag: str -> str {
        "snap_counters ${side}-${tag}\n" if cache else ""
    }
    # The warm-up passes when at least 99% of the hot data set is cached; the exact cached bytes and fraction go
    # to warmup-<side>.json. DACS fills its cache asynchronously and best-effort, so it can end a little short of
    # 100% (1022 of 1024 blocks was seen). The binding proof that the cache is used is the hot phase (hits > 0, at
    # most 1% re-uploads or UFS bytes, hot Blob egress at most 1%), not this check. DACS uses the CUMULATIVE
    # Upload total of the after-warm-up snapshot (the Cache is created fresh in the preceding step, so the total
    # is the cached amount), not the before/after delta: re-running this step on an already-warm cache passes.
    # Alluxio likewise uses the ABSOLUTE cached-pages gauge total of the after-warm-up snapshot (summed over the
    # workers, 4 MiB pages): the workers and their page store are created fresh in the preceding steps and the
    # cold, concurrent and re-read data are read only after the warm-up.
    warmCheck = """
    (counter_total($after | prometheus_samples; "alluxio_data_cached_pages"; [])) as $pages
    | if $pages == null then failed("the warm-up check needs the alluxio_data_cached_pages gauge of the workers")
      else ($pages * 4194304) as $cached
      | if $cached * 100 >= $hot_bytes * 99 then {cached_bytes: $cached, hot_bytes: $hot_bytes, fraction: ($cached / $hot_bytes)}
        else failed("the warm-up cached " + ($cached | tostring) + " bytes in Alluxio in total, less than 99% of the " + ($hot_bytes | tostring) + " byte hot data set")
        end
      end""" if side == "alluxio" else """
    (counter_total($after | prometheus_samples; "cache_server_request_counter"; ["request_type=\\"Upload\\"", "status=\\"Success\\""])) as $blocks
    | if $blocks == null then failed("the warm-up check needs the DACS Upload counter of the servers")
      else ($blocks * 1048576) as $cached
      | if $cached * 100 >= $hot_bytes * 99 then {cached_bytes: $cached, hot_bytes: $hot_bytes, fraction: ($cached / $hot_bytes)}
        else failed("the warm-up uploaded " + ($cached | tostring) + " bytes to DACS in total, less than 99% of the " + ($hot_bytes | tostring) + " byte hot data set")
        end
      end"""
    # Alluxio: the warm-up must fill the caches of all the workers that the hot reads use. 300 s covers a worker
    # that is still restarting.
    workersReady = PHASES_WAIT_SHELL + """
alluxio_workers_ready() {
    local pods
    pods="$(kubectl get pods -n "$POSIX_NS" -o json)" || return 1
    jq -e --argjson want ${POSIX_CACHE_COUNT} '[.items[] | select(.metadata.name | startswith("alluxio-worker-"))] as $workers
        | ($workers | length) == $want
        and all($workers[]; .status.phase == "Running" and any(.status.conditions[]?; .type == "Ready" and .status == "True"))' \\
        <<< "$pods" > /dev/null
}
wait_until 300 "exactly ${POSIX_CACHE_COUNT} Ready alluxio-worker pods" alluxio_workers_ready
""" if side == "alluxio" else ""
    warmUp = ("""
# 1. Warm-up.
""" + workersReady + """POSIX_GROUP=warmup
snap_counters ${side}-warmup-before
eb_run ${side}-warmup ${side} warmup all ${warmLimit} -r -b 16M -t 8 -s ${hotFileBytes} $hot_files
eb_result warmup "$POSIX_RESULT/${side}-warmup.txt" > /dev/null
""" + ("dacs_settle\n" if side == "dacs" else "") + """# The cache's own count can trail the reads by a few seconds, so the check is repeated for up to 120 s.
warm_deadline=$((SECONDS + 120))
until snap_counters ${side}-warmup-after &&
    counters_jq ${side}-warmup '${warmCheck}' > "$POSIX_RESULT/warmup-${side}.json" 2> "$POSIX_WORK/warmup-check.err"; do
    if (( SECONDS >= warm_deadline )); then
        cat "$POSIX_WORK/warmup-check.err" >&2
        fail "the ${side} cache does not hold the hot data set 120 s after the warm-up"
    fi
    sleep 10
done
sleep 120
""") if cache else ""
    hitCheck = ("""counters_jq ${side}-hot '{before: $before, after: $after} | counter_delta | . + {hot_bytes: $hot_bytes} | validate_cache_hits("${side}")' \\
    > "$POSIX_RESULT/hot-counters-${side}.json" || fail "the ${side} hot reads are not proven to come from the cache"
""") if cache else ""
    # Counter snapshots around a concurrent rep and their difference, on the cache sides; indented for cc_run.
    ccBefore = "    snap_counters ${side}-23-24-r$rep-before\n" if cache else ""
    ccAfter = "    snap_counters ${side}-23-24-r$rep-after\n    record_cc_counters \"$rep\"\n" if cache else ""
    ccCounters = ("""# Appends the counter differences of concurrent rep <rep> to counters-${side}.jsonl.
# Usage: record_cc_counters <rep>
record_cc_counters() {
    counters_jq ${side}-23-24-r$1 '{side: "${side}", scenario: "23-24", rep: ($rep | tonumber)} + ({before: $before, after: $after} | counter_delta)' \\
        --arg rep "$1" >> "$POSIX_RESULT/counters-${side}.jsonl"
}
""") if cache else ""
    # BlobFuse2 with the CSI defaults, Alluxio FUSE with direct I/O off: both let the second read hit the page cache.
    rereadMount = MountPosixVolume("bf2", 0, container, elbenchoImage, checksDir) if side == "bf2" else SetAlluxioDirectIo(False, "${checksDir}/clients-fuse.yaml", elbenchoImage) + "wait_hot_listing\n"
    rereadShell = "" if len(reread) == 0 else ("""
# 5. Re-read: the same node reads ${side}-m8 twice, on a mount that keeps the kernel page cache; the node's page cache
# is dropped before the first read.
""" + rereadMount + """POSIX_GROUP=reread
sleep 70
pods="$(client_pods)"
reread_pod="$(head -n 1 <<< "$pods")"
reread_node="$(kubectl get pod "$reread_pod" -n "$POSIX_NS" -o jsonpath='{.spec.nodeName}')"
[[ -n "$reread_node" ]] || fail "could not find the node of $reread_pod"
reread_file="$(files_of ${side}-m8 1)"
reread_run() {
    eb_local ${side}-${reread[0].id}-r$1 ${side} ${reread[0].id} "$1" "$reread_pod" ${rereadLimit} -r -b ${reread[0].blockSize} -t ${reread[0].threads} -s ${POSIX_REREAD_GIB * 1073741824} $reread_file
    record_run reread ${side}-${reread[0].id}-r$1
}
drop_page_cache "$reread_node"
""" + snap("${reread[0].id}-before") + """reread_run 1
""" + snap("${reread[0].id}-between") + """sleep 70
reread_run 2
""" + snap("${reread[0].id}-after"))
    hotWant = json.encode({"hot": len(hot) * POSIX_REPS})
    hotIndexWant = json.encode(({"warmup-all": 1} if cache else {}) | {"hot-all": 1, "hot": len(hot) * POSIX_REPS})
    # A rest step that runs again after its re-read finds BlobFuse2 mounted for the re-read. The Blob sides therefore
    # check, before the rest step changes anything, that the volume still has the mount of the hot step, which the
    # cold and concurrent reads use.
    coldOptions = json.encode(PosixMountOptions("bf2", cold[0].bf2BlockMiB) if side == "bf2" else PosixMountOptions("dacs", 1))
    mountCheck = """mount_options="$(kubectl get pv posix-data -o json | jq -c '.spec.mountOptions')" ||
    fail "could not read the mount options of the volume posix-data"
jq -en --argjson got "$mount_options" --argjson want '${coldOptions}' '$got == $want' > /dev/null ||
    fail "the volume posix-data is mounted with $mount_options, not with the options of the ${side} cold and concurrent reads; run the hot step of ${side} again first"
""" if side != "alluxio" else ""
    # The rest step starts from the warm-up and hot reads of the hot step and keeps them; it drops what an earlier
    # attempt of itself left (cold, concurrent and re-read lines and runs, concurrent counters).
    restPrep = """
[[ -s "$POSIX_RESULT/runs-${side}.jsonl" && -s "$POSIX_RESULT/index.jsonl" ]] ||
    fail "the hot reads of ${side} have not run: runs-${side}.jsonl or index.jsonl is missing or empty"
""" + mountCheck + """jq -c --arg side ${side} 'select(.side != $side or .group == "warmup" or .group == "hot")' "$POSIX_RESULT/index.jsonl" > "$POSIX_WORK/index.jsonl"
mv -- "$POSIX_WORK/index.jsonl" "$POSIX_RESULT/index.jsonl"
jq -c 'select(.group == "hot")' "$POSIX_RESULT/runs-${side}.jsonl" > "$POSIX_WORK/runs.jsonl"
mv -- "$POSIX_WORK/runs.jsonl" "$POSIX_RESULT/runs-${side}.jsonl"
hot_runs="$(jq -cs 'map(.group) | group_by(.) | map({(.[0]): length}) | add // {}' "$POSIX_RESULT/runs-${side}.jsonl")" ||
    fail "could not read runs-${side}.jsonl"
jq -en --argjson got "$hot_runs" --argjson want '${hotWant}' '$got == $want' > /dev/null ||
    fail "runs-${side}.jsonl holds the groups $hot_runs, not exactly the hot runs ${hotWant}"
hot_index="$(jq -cs --arg side ${side} 'map(select(.side == $side) | if .rep == "all" then .scenario + "-all" else .group end) | group_by(.) | map({(.[0]): length}) | add // {}' "$POSIX_RESULT/index.jsonl")" ||
    fail "could not read index.jsonl"
jq -en --argjson got "$hot_index" --argjson want '${hotIndexWant}' '$got == $want' > /dev/null ||
    fail "index.jsonl holds the ${side} entries $hot_index, not exactly ${hotIndexWant}"
""" + ("""[[ -s "$POSIX_RESULT/warmup-${side}.json" && -s "$POSIX_RESULT/hot-counters-${side}.json" ]] ||
    fail "the warm-up or hot counter proof of ${side} is missing"
: > "$POSIX_RESULT/counters-${side}.jsonl"
""" if cache else "")
    azure.AzCli(
        serviceConnection
        ("Run the POSIX warm-up and hot reads on " if part == "hot" else "Run the POSIX cold, concurrent and re-read scenarios on " if len(reread) > 0 else "Run the POSIX cold and concurrent reads on ") + {bf2 = "BlobFuse2", dacs = "BlobFuse2 with DACS", alluxio = "Alluxio FUSE"}[side]
        PosixShellSetup(workDir, resultDir) + POSIX_RUNTIME_SHELL + """
# The data set's file paths whose names start with a prefix, space-separated (names have no spaces), failing
# unless there are exactly <count>. checks.jq posix_dataset owns the names.
# Usage: files_of <prefix> <count>
files_of() {
    local files
    files="$(jq -nr -L "${checksDir}" -L "${checksDir}/.." --arg prefix "$1" \\
        --argjson sides '${POSIX_DATASET_SIDES}' \\
        'include "checks"; posix_dataset(${POSIX_HOT_FILES}; ${POSIX_HOT_FILE_MIB}; ${POSIX_COLD_FILES}; ${POSIX_CC_FILES}; ${POSIX_BIG_FILE_GIB}; ${POSIX_REREAD_GIB}; $sides)[] | select(.name | startswith($prefix)) | "/data/" + .name' |
        paste -sd' ' -)"
    [[ "$(wc -w <<< "$files" | tr -d ' ')" == "$2" ]] || fail "expected $2 data set files named $1*, found: $files"
    echo "$files"
}
# Validates one elbencho result for its group and prints the parsed result.
# Usage: eb_result <group> <result file>
eb_result() {
    jq -Rse -L "${checksDir}" -L "${checksDir}/.." --arg group "$1" \\
        'include "checks"; validate_elbencho_run($group; ${POSIX_REP_SECONDS})' "$2" ||
        fail "$2 is not a valid result of a $1 run"
}
# Validates the run with this label and appends its index line plus the parsed result to runs-${side}.jsonl.
# Usage: record_run <group> <label>
record_run() {
    local result line
    result="$(eb_result "$1" "$POSIX_RESULT/$2.txt")"
    line="$(jq -cs --arg name "$2" --argjson result "$result" \\
        'map(select(.label == $name)) | if length == 1 then .[0] + {result: $result} else error("ALLUXIO POSIX READ FAILED: not exactly one index line labelled " + $name) end' \\
        "$POSIX_RESULT/index.jsonl")" || fail "could not record run $2"
    echo "$line" >> "$POSIX_RESULT/runs-${side}.jsonl"
}
# Runs a checks.jq filter over the counter snapshots <tag>-before and <tag>-after, given as $before and $after,
# with $hot_bytes the size of the hot data set (hot files x file size). Extra jq arguments follow the filter.
# Usage: counters_jq <tag> <filter> [jq args...]
counters_jq() {
    local tag="$1" filter="$2"
    shift 2
    jq -nc -L "${checksDir}" -L "${checksDir}/.." \\
        --rawfile before "$POSIX_RESULT/counters-$tag-before.prom" --rawfile after "$POSIX_RESULT/counters-$tag-after.prom" \\
        --argjson hot_bytes ${hotBytes} "$@" "include \\"checks\\"; $filter"
}
# One hot rep: random reads over all hot files for ${POSIX_REP_SECONDS} s. --randamount 2G is the amount of one pass
# of the whole job (all hosts together, in file mode); --infloop repeats passes until --timelimit ends the rep,
# so every rep measures the same length of time whatever the speed.
# Usage: hot_run <scenario> <rep> <block size> <threads>
hot_run() {
    local label="${side}-$1-r$2"
    eb_run "$label" ${side} "$1" "$2" ${hotLimit} -r --rand --randamount 2G -b "$3" -t "$4" -s ${hotFileBytes} \\
        --timelimit ${POSIX_REP_SECONDS} --infloop --lat --latpercent $hot_files
    record_run hot "$label"
}

""" + ("""
: > "$POSIX_RESULT/runs-${side}.jsonl"
hot_files="$(files_of p ${POSIX_HOT_FILES})"
""" + (MountPosixVolume("dacs", 1, container, elbenchoImage, checksDir) if side == "dacs" else "") + ("client_list > /dev/null\nwait_hot_listing\n" if side == "alluxio" else "") + warmUp + """
# 2. Hot.
""" + snap("hot-before") + "POSIX_GROUP=hot\n" + hotShell + snap("hot-after") + """# The one hot entry of this side for the Blob egress attribution, from the first hot start to the last hot end.
hot_span="$(jq -cs --arg side ${side} \\
    'map(select(.side == $side and .group == "hot" and .rep != "all")) |
    if length == 0 then error("ALLUXIO POSIX READ FAILED: no hot run in the index") else
    {"label": ($side + "-hot"), side: $side, scenario: "hot", rep: "all", start: (map(.start) | min), "end": (map(.end) | max), group: "hot"} end' \\
    "$POSIX_RESULT/index.jsonl")"
echo "$hot_span" >> "$POSIX_RESULT/index.jsonl"
""" + hitCheck if part == "hot" else restPrep + """
# 3. Cold: every rep reads a set of this side that nothing has read before. Three minutes of quiet before the
# first rep.
POSIX_GROUP=cold
sleep 180
for rep in $(seq 1 ${POSIX_REPS}); do
    (( rep == 1 )) || sleep 70
    cold_files="$(files_of "${side}-cold-r$rep-" ${POSIX_COLD_FILES})"
    # The whole job reads 1536 MiB at random offsets of the set and then ends (no --infloop); --timelimit ${coldSeconds}
    # stops a rep that is slower than that, which the summary then compares by IOPS and marks as timed out.
    eb_run ${side}-${cold[0].id}-r$rep ${side} ${cold[0].id} "$rep" ${coldLimit} -r --rand --randamount 1536M -b ${cold[0].blockSize} -t ${cold[0].threads} -s ${bigFileBytes} \\
        --timelimit ${coldSeconds} --lat --latpercent $cold_files
    record_run cold ${side}-${cold[0].id}-r$rep
""" + dacsSettle + """done

# 4. Concurrent: every client reads the whole set ${side}-cc-r<rep> at the same time (eb_local_all).
POSIX_GROUP=concurrent
sleep 70
${ccCounters}cc_run() {
    local rep="$1" files path pods pod
    files="$(files_of "${side}-cc-r$rep-" ${POSIX_CC_FILES})"
    # $files is split on purpose: the first file is eb_local_all's path, the others follow the options.
    set -- $files
    path="$1"
    shift
${ccBefore}    eb_local_all ${side}-${concurrent[0].id}-r$rep ${side} "$rep" ${ccLimit} "$path" -r -b ${concurrent[0].blockSize} -t ${concurrent[0].threads} -s ${bigFileBytes} "$@"
${ccAfter}    pods="$(client_pods)"
    for pod in $pods; do
        record_run concurrent ${side}-${concurrent[0].id}-r$rep-$pod
    done
""" + dacsSettle + """}
for rep in $(seq 1 ${POSIX_REPS}); do
    (( rep == 1 )) || sleep 70
    cc_run "$rep"
done
""" + rereadShell)
        stepName = "posix_${side}_${part}"
        timeoutInMinutes = POSIX_STEP_TIMEOUT_MINUTES
    )
}
