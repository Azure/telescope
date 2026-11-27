ALLUXIO_TAG = "AI-3.8-15.1.28"
OPERATOR_TAG = "3.7.6"
OBJECT_COUNT = 16
OBJECT_SIZE_BYTES = 64 * 1024 * 1024

# The command of ShellSetup's EXIT trap: it removes the scratch files that can hold secret-bearing output. A
# step that sets its own EXIT trap runs this command in it too.
ShellCleanup = lambda workDir: str -> str {
    'rm -f -- "${workDir}/command.out" "${workDir}/command.err" "${workDir}/blob.bin" "${workDir}/helm-registry.json"'
}

# Expand the same secret-safe shell setup into each independent pipeline step.
ShellSetup = lambda workDir: str, resultDir: str -> str {
    """
set +x
set -Eeuo pipefail
umask 077
mkdir -p -- "${workDir}" "${resultDir}"
chmod 700 "${workDir}"
export AZURE_CORE_ONLY_SHOW_ERRORS=true AZURE_CORE_OUTPUT=json
export KUBECONFIG="$HOME/.kube/config"
# Avoid WebSocket stream closures during long-running AKS exec commands.
export KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false
fail() {
    echo "ALLUXIO WARP FAILED: $*" >&2
    exit 1
}
trap 'echo "ALLUXIO WARP FAILED: command at line $LINENO exited with status $?" >&2' ERR
trap '${ShellCleanup(workDir)}' EXIT
"""
}

SecretCommands = lambda workDir: str -> str {
    """
private_command() {
    if "$@" > "${workDir}/command.out" 2> "${workDir}/command.err"; then
        cat "${workDir}/command.out"
    else
        fail "$1 failed; secret-bearing output withheld"
    fi
}
require_secret() {
    [[ -n "\${!1:-}" && "\${!1}" != '$('* ]] || fail "Required secret pipeline variable $1 is missing"
}
"""
}

ResourceCommands = lambda workDir: str -> str {
    SecretCommands(workDir) + """
resource_failure_details() {
    local kind="$1" name="$2" pods pod
    # Project status only: the resource spec and annotations can contain the license or SAS.
    if ! kubectl get "$kind" "$name" -n alx-ns -o json |
        jq '{
            name: .metadata.name,
            status: (.status | {phase, state, reason, message, error, conditions})
        } | walk(if type == "string" then
            reduce ([env.ALLUXIO_LICENSE_STRING, env.BLOB_SAS][] | select(. != null and . != "")) as $secret
                (.; split($secret) | join("<redacted>"))
            else . end)' | redact >&2; then
        echo "Could not collect status for $kind/$name" >&2
    fi
    if [[ "$kind" == license ]]; then
        if ! pods="$(kubectl get pods -n alluxio-operator -o json |
            jq -r '.items[] | select(.metadata.name | startswith("alluxio-license-controller-")) | .metadata.name')"; then
            echo "Could not list the license-controller pods" >&2
            return 0
        fi
        [[ -n "$pods" ]] || echo "No license-controller pods found" >&2
        for pod in $pods; do
            echo "Recent license-controller logs: $pod" >&2
            if ! kubectl logs -n alluxio-operator "$pod" --all-containers=true --tail=100 --since=10m |
                jq -Rs -r 'reduce ([env.ALLUXIO_LICENSE_STRING, env.BLOB_SAS][] | select(. != null and . != "")) as $secret
                    (.; split($secret) | join("<redacted>"))' | redact >&2; then
                echo "Could not collect logs for $pod" >&2
            fi
        done
    fi
}
wait_phase() {
    local kind="$1" name="$2" field="$3" expected="$4" phase deadline=$((SECONDS + 900))
    while :; do
        phase="$(kubectl get \\
            "$kind" "$name" -n alx-ns -o "jsonpath={.status.$field}")"
        [[ "$phase" != "$expected" ]] || return 0
        case "$phase" in
            Failed|Error|Terminated)
                resource_failure_details "$kind" "$name"
                fail "$kind/$name failed; see status and controller diagnostics above"
                ;;
        esac
        if (( SECONDS >= deadline )); then
            resource_failure_details "$kind" "$name"
            fail "$kind/$name did not reach $expected before timeout; see diagnostics above"
        fi
        sleep 10
    done
}
"""
}

REDACT_OUTPUT = """
redact() {
    local line secret
    while IFS= read -r line || [[ -n "$line" ]]; do
        for secret in "\${ALLUXIO_LICENSE_STRING:-}" "\${BLOB_SAS:-}"; do
            if [[ -n "$secret" ]]; then line="\${line//"$secret"/<redacted>}"; fi
        done
        printf '%s\\n' "$line"
    done
}
"""

AlluxioCommands = lambda checksDir: str, resultDir: str -> str {
    REDACT_OUTPUT + """
alluxio() {
    kubectl exec -n alx-ns alluxio-coordinator-0 \\
        -c alluxio-coordinator -- alluxio "$@"
}
client_exec() {
    kubectl exec -n alx-ns warp-client -c warp -- "$@"
}
cache_report() {
    alluxio fs check-cached --path /blob --recursive --limit ${OBJECT_COUNT + 1} |
        redact > "${resultDir}/cache-$1.txt"
    jq -Rse -L "${checksDir}" 'include "checks"; cache_counts(${OBJECT_COUNT})' "${resultDir}/cache-$1.txt"
}
"""
}
