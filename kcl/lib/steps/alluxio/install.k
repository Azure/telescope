import azure_pipelines.ap.steps
import lib.steps.azure

InstallOperator = lambda serviceConnection: str, registryId: str, registrySubscription: str, operatorImage: str, operatorChart: str, workDir: str, resultDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Install the Alluxio operator"
        ShellSetup(workDir, resultDir) + SecretCommands(workDir) + """
registry="$(az acr show --ids "${registryId}")"
registry_name="$(jq -er '.name' <<< "$registry")"
login_server="$(jq -er '.loginServer' <<< "$registry")"
registry_token="$(private_command az acr login \\
    --name "$registry_name" \\
    --subscription "${registrySubscription}" \\
    --expose-token --query accessToken --output tsv)"
printf '%s' "$registry_token" |
    private_command helm registry login "$login_server" \\
        --username 00000000-0000-0000-0000-000000000000 \\
        --password-stdin --registry-config "${workDir}/helm-registry.json" > /dev/null
unset registry_token
kubectl create namespace alx-ns
jq -n --arg image "${operatorImage}" --arg tag "${OPERATOR_TAG}" \\
    '{global: {image: $image, imageTag: $tag}}' > "${workDir}/operator-values.json"
helm install operator "${operatorChart}" \\
    --version "${OPERATOR_TAG}" \\
    --registry-config "${workDir}/helm-registry.json" \\
    --namespace alluxio-operator \\
    --create-namespace \\
    --values "${workDir}/operator-values.json" \\
    --wait
for crd in alluxioclusters licenses underfilesystems; do
    kubectl wait --for=condition=Established \\
        "crd/$crd.k8s-operator.alluxio.com" --timeout=120s
done
"""
        stepName = "alluxio_operator"
    )
}

CreateAlluxioCluster = lambda alluxioImage: str, manifest: str, licenseManifest: str, workDir: str, resultDir: str -> steps.Bash {
    steps.Bash {
        name = "alluxio_cluster"
        displayName = "Create Alluxio and apply the deployment license"
        bash = ShellSetup(workDir, resultDir) + ResourceCommands(workDir) + REDACT_OUTPUT + """
require_secret ALLUXIO_LICENSE_STRING
patch="$(jq -n --arg image "${alluxioImage}" --arg tag "${ALLUXIO_TAG}" \\
    '{spec: {image: $image, imageTag: $tag}}')"
cluster="$(kubectl patch --local --type=merge -f "${manifest}" -p "$patch" -o yaml)"
printf '%s\\n' "$cluster" | kubectl create --dry-run=server --validate=strict -f - > /dev/null
printf '%s\\n' "$cluster" | kubectl create -f - > /dev/null
license="$(jq -n '{spec: {licenseString: env.ALLUXIO_LICENSE_STRING}}' |
    kubectl patch --local --type=merge -f "${licenseManifest}" \\
        --patch-file /dev/stdin -o yaml 2> >(redact >&2))"
printf '%s\\n' "$license" |
    kubectl create --dry-run=server --validate=strict -f - > /dev/null 2> >(redact >&2)
printf '%s\\n' "$license" | kubectl create -f - > /dev/null 2> >(redact >&2)
unset license
wait_phase license alluxio-license phase Completed
wait_phase alluxiocluster alluxio clusterPhase Ready
for pod in alluxio-coordinator-0 alluxio-worker-0; do
    kubectl wait -n alx-ns --for=condition=Ready "pod/$pod" --timeout=600s
done
"""
        env = {
            ALLUXIO_LICENSE_STRING = "$(ALLUXIO_LICENSE_STRING)"
        }
    }
}

MountBlobStorage = lambda storageAccount: str, manifest: str, workDir: str, resultDir: str -> steps.Bash {
    steps.Bash {
        name = "alluxio_mount"
        displayName = "Mount Azure Blob in Alluxio"
        bash = ShellSetup(workDir, resultDir) + ResourceCommands(workDir) + REDACT_OUTPUT + """
require_secret BLOB_SAS
ufs="$(jq -n --arg account "${storageAccount}" '{
    spec: {path: ("abfs://" + $account + ".blob.core.windows.net/warp-data/"),
           mountOptions: {"alluxio.underfs.abfs.sas.token": env.BLOB_SAS}}
}' | kubectl patch --local --type=merge -f "${manifest}" \\
    --patch-file /dev/stdin -o yaml 2> >(redact >&2))"
printf '%s\\n' "$ufs" |
    kubectl create --dry-run=server --validate=strict -f - > /dev/null 2> >(redact >&2)
printf '%s\\n' "$ufs" | kubectl create -f - > /dev/null 2> >(redact >&2)
unset ufs
wait_phase ufs alluxio-blob phase Ready
kubectl exec -n alx-ns alluxio-coordinator-0 \\
    -c alluxio-coordinator -- alluxio fs ls /blob | redact
"""
        env = {
            BLOB_SAS = "$(BLOB_SAS)"
        }
    }
}
