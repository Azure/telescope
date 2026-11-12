ALLUXIO_TAG = "AI-3.8-15.1.28"
OPERATOR_TAG = "3.7.6"
WARP_VERSION = "1.3.1"
WARP_SHA256 = "5a84ed6efdd8390f77e5990dc43722868b026c7574f41ffb1b7289795aadb603"

# Expand the same secret-safe shell setup into each independent pipeline step.
ShellSetup = lambda workDir: str, resultDir: str -> str {
    """
set +x
set -Eeuo pipefail
umask 077
work_dir="${workDir}"
result_dir="${resultDir}"
mkdir -p -- "$work_dir" "$result_dir"
chmod 700 "$work_dir"
export AZURE_CORE_ONLY_SHOW_ERRORS=true AZURE_CORE_OUTPUT=json
fail() {
    echo "ALLUXIO WARP FAILED: $*" >&2
    exit 1
}
trap 'echo "ALLUXIO WARP FAILED: command at line $LINENO exited with status $?" >&2' ERR
trap 'rm -f -- "$work_dir/command.out" "$work_dir/command.err" "$work_dir/blob.bin" "$work_dir/helm-registry.json"' EXIT
"""
}

SECRET_COMMANDS = """
private_command() {
    if "$@" > "$work_dir/command.out" 2> "$work_dir/command.err"; then
        cat "$work_dir/command.out"
    else
        fail "$1 failed; secret-bearing output withheld"
    fi
}
require_secret() {
    [[ -n "\${!1:-}" && "\${!1}" != '$('* ]] || fail "Required secret pipeline variable $1 is missing"
}
"""

RESOURCE_COMMANDS = SECRET_COMMANDS + """
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
