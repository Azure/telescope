ALLUXIO_TAG = "AI-3.8-15.1.28"
OPERATOR_TAG = "3.7.6"

# Expand the same secret-safe shell setup into each independent pipeline step.
ShellSetup = lambda workDir: str, resultDir: str -> str {
    """
set +x
set -Eeuo pipefail
umask 077
mkdir -p -- "${workDir}" "${resultDir}"
chmod 700 "${workDir}"
export AZURE_CORE_ONLY_SHOW_ERRORS=true AZURE_CORE_OUTPUT=json
fail() {
    echo "ALLUXIO WARP FAILED: $*" >&2
    exit 1
}
trap 'echo "ALLUXIO WARP FAILED: command at line $LINENO exited with status $?" >&2' ERR
trap 'rm -f -- "${workDir}/command.out" "${workDir}/command.err" "${workDir}/blob.bin" "${workDir}/helm-registry.json"' EXIT
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
wait_phase() {
    local kind="$1" name="$2" field="$3" expected="$4" phase deadline=$((SECONDS + 900))
    while :; do
        phase="$(kubectl get \\
            "$kind" "$name" -n alx-ns -o "jsonpath={.status.$field}")"
        [[ "$phase" != "$expected" ]] || return 0
        case "$phase" in
            Failed|Error|Terminated) fail "$kind/$name failed; inspect securely in cluster" ;;
        esac
        (( SECONDS < deadline )) || fail "$kind/$name did not reach $expected before timeout"
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
    alluxio fs check-cached --path /blob --recursive --limit 17 |
        redact > "${resultDir}/cache-$1.txt"
    jq -Rse -L "${checksDir}" 'include "checks"; cache_counts' "${resultDir}/cache-$1.txt"
}
"""
}
