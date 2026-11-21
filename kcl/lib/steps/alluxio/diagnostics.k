import azure_pipelines.ap.steps
import lib.steps.azure

# Pod states of the Alluxio and operator namespaces; no logs, no secrets. Runs even when the job failed.
# logPods adds the log tail of every container and the `kubectl describe` of more pods, given as
# "<namespace>/<pod name prefix>", in resultDir/diagnostics. A SAS signature in them is replaced, because the
# results are published; a description shows Secret references, not their values. A namespace or pod that no
# longer exists is skipped.
CollectDiagnostics = lambda serviceConnection: str, workDir: str, resultDir: str, logPods: [str] = [] -> steps.Step {
    selectors = " ".join(['"${selector}"' for selector in logPods])
    logShell = """
mkdir -p "${resultDir}/diagnostics"
# Replaces the value of every sig= query parameter, in any letter case.
redact_signatures() {
    sed -E 's/[Ss][Ii][Gg]=[^&[:space:]"]*/sig-redacted/g'
}
for selector in ${selectors}; do
    namespace="\${selector%%/*}"
    prefix="\${selector#*/}"
    pods="$(kubectl get pods -n "$namespace" -o name 2> /dev/null | sed -n "s|^pod/\\($prefix.*\\)$|\\1|p")" || true
    for pod in $pods; do
        kubectl describe pod "$pod" -n "$namespace" 2>&1 | redact_signatures > "${resultDir}/diagnostics/$namespace-$pod.describe.txt" || true
        # The last 5000 lines of each container cover the end of a failed phase and keep the artifact small.
        kubectl logs "$pod" -n "$namespace" --all-containers=true --prefix=true --tail=5000 2>&1 |
            redact_signatures > "${resultDir}/diagnostics/$namespace-$pod.log" || true
    done
done
""" if logPods else ""
    azure.AzCli(
        serviceConnection
        "Collect safe deployment diagnostics"
        ShellSetup(workDir, resultDir) + """
if [[ ! -s "$KUBECONFIG" ]]; then
    echo '{"cluster_access":"not established"}' > "${resultDir}/diagnostics.json"
    exit 0
fi
for namespace in alx-ns alluxio-operator; do
    kubectl get pods -n "$namespace" -o json |
        jq --arg namespace "$namespace" '{
            ($namespace): [.items[] | {
                name: .metadata.name, node: .spec.nodeName, phase: .status.phase,
                containers: [(.status.containerStatuses // []) + (.status.initContainerStatuses // []) | .[] |
                    {name, ready, restarts: .restartCount,
                     state: (.state | with_entries(.value |= {reason, exitCode}))}]
            }]
        }' > "${workDir}/diagnostics-$namespace.json"
done
jq -s 'add' "${workDir}/diagnostics-alx-ns.json" "${workDir}/diagnostics-alluxio-operator.json" \\
    > "${resultDir}/diagnostics.json"
""" + logShell
        condition = "always()"
        stepName = "alluxio_diagnostics"
    )
}
