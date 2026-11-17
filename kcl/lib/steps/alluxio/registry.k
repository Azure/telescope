import azure_pipelines.ap.steps
import lib.steps.azure

ConfigureImagePullAccess = lambda serviceConnection: str, registryId: str, registrySubscription: str, workDir: str, resultDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Configure short-lived ACR image pull credentials"
        ShellSetup(workDir, resultDir) + SecretCommands(workDir) + """
# The shared registry has a delete lock; keep credentials inside the disposable cluster instead of creating RBAC grants.
registry="$(az acr show --name "${registryId.split("/")[-1]}" --subscription "${registrySubscription}")"
login_server="$(jq -er '.loginServer' <<< "$registry")"
REGISTRY_TOKEN="$(private_command az acr login \\
    --name "${registryId.split("/")[-1]}" \\
    --subscription "${registrySubscription}" \\
    --expose-token --query accessToken --output tsv)"
export REGISTRY_TOKEN
for namespace in alx-ns alluxio-operator; do
    kubectl create namespace "$namespace"
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
        private_command kubectl create --dry-run=server --validate=strict -f - > /dev/null
    printf '%s\\n' "$pull_secret" | private_command kubectl create -f - > /dev/null
done
unset REGISTRY_TOKEN pull_secret
"""
        stepName = "alluxio_acr_credentials"
    )
}
