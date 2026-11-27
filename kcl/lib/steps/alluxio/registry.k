import azure_pipelines.ap.steps
import lib.steps.azure

# Creates the namespaces alx-ns and alluxio-operator, each with the pull Secret alluxio-acr. The registry
# token in the Secret expires 3 hours after it is issued (az acr login --expose-token). A pipeline that pulls
# images later than that runs the step again with isRefresh, which replaces the Secret in the existing
# namespaces.
ConfigureImagePullAccess = lambda serviceConnection: str, registryName: str, registrySubscription: str, workDir: str, resultDir: str, isRefresh: bool = False -> steps.Step {
    azure.AzCli(
        serviceConnection
        ("Refresh" if isRefresh else "Configure") + " short-lived ACR image pull credentials"
        ShellSetup(workDir, resultDir) + SecretCommands(workDir) + """
# The shared registry has a delete lock; keep credentials inside the disposable cluster instead of creating RBAC grants.
login_server="$(az acr show --name "${registryName}" --subscription "${registrySubscription}" | jq -er '.loginServer')"
REGISTRY_TOKEN="$(private_command az acr login \\
    --name "${registryName}" \\
    --subscription "${registrySubscription}" \\
    --expose-token --query accessToken --output tsv)"
export REGISTRY_TOKEN
for namespace in alx-ns alluxio-operator; do
    ${'kubectl delete secret alluxio-acr -n "$namespace" --ignore-not-found > /dev/null' if isRefresh else 'kubectl create namespace "$namespace"'}
    pull_secret="$(jq -n --arg server "$login_server" --arg namespace "$namespace" '{
        apiVersion: "v1", kind: "Secret",
        metadata: {name: "alluxio-acr", namespace: $namespace},
        type: "kubernetes.io/dockerconfigjson",
        stringData: {".dockerconfigjson": ({
            auths: {($server): {
                username: "00000000-0000-0000-0000-000000000000",
                password: env.REGISTRY_TOKEN,
                auth: ("00000000-0000-0000-0000-000000000000:" + env.REGISTRY_TOKEN | @base64)
            }}
        } | tojson)}
    }')"
    printf '%s\\n' "$pull_secret" |
        private_command kubectl create --validate=strict -f - > /dev/null
done
unset REGISTRY_TOKEN pull_secret
"""
        stepName = "alluxio_acr_credentials" + ("_refresh" if isRefresh else "")
    )
}
