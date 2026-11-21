import azure_pipelines.ap.steps
import lib.steps.azure

# Pod states of the Alluxio and operator namespaces; no logs, no secrets. Runs even when the job failed.
CollectDiagnostics = lambda serviceConnection: str, workDir: str, resultDir: str -> steps.Step {
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
"""
        condition = "always()"
        stepName = "alluxio_diagnostics"
    )
}
