import azure_pipelines.ap.steps
import lib.steps.azure

RESOURCE_COMMANDS = SECRET_COMMANDS + """
create_private_resource() {
    private_command timeout 180 kubectl create --dry-run=server --validate=strict -f "$1" > /dev/null
    private_command timeout 180 kubectl create -f "$1" > /dev/null
}
wait_phase() {
    local kind="$1" name="$2" field="$3" expected="$4" phase deadline=$((SECONDS + 900))
    while :; do
        phase="$(timeout 70 kubectl --request-timeout=60s get \\
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

InstallOperator = lambda serviceConnection: str, operatorChart: str, workDir: str, resultDir: str -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Install the Alluxio operator"
        ShellSetup(workDir, resultDir) + LOAD_CONFIG + SECRET_COMMANDS + """
export KUBECONFIG="${workDir}/kubeconfig"
registry="$(timeout 300 az acr show --ids "$acr_resource_id")"
registry_name="$(jq -er '.name' <<< "$registry")"
login_server="$(jq -er '.loginServer' <<< "$registry")"
registry_token="$(private_command timeout 300 az acr login \\
    --name "$registry_name" \\
    --subscription "$acr_subscription" \\
    --expose-token --query accessToken --output tsv)"
printf '%s' "$registry_token" |
    private_command timeout 300 helm registry login "$login_server" \\
        --username 00000000-0000-0000-0000-000000000000 \\
        --password-stdin --registry-config "$work_dir/helm-registry.json" > /dev/null
unset registry_token
timeout 70 kubectl --request-timeout=60s create namespace alx-ns
jq -n --arg image "$operator_image" --arg tag "${OPERATOR_TAG}" \\
    '{global: {image: $image, imageTag: $tag}}' > "$work_dir/operator-values.json"
timeout 960 helm install operator "${operatorChart}" \\
    --version "${OPERATOR_TAG}" \\
    --registry-config "$work_dir/helm-registry.json" \\
    --namespace alluxio-operator \\
    --create-namespace \\
    --values "$work_dir/operator-values.json" \\
    --wait \\
    --timeout 15m
for crd in alluxioclusters licenses underfilesystems; do
    timeout 180 kubectl wait --for=condition=Established \\
        "crd/$crd.k8s-operator.alluxio.com" --timeout=120s
done
"""
        stepName = "alluxio_operator"
    )
}

CreateAlluxioCluster = lambda workDir: str, resultDir: str -> steps.Bash {
    BashStep(
        "Create Alluxio and apply the deployment license"
        LOAD_CONFIG + RESOURCE_COMMANDS + """
require_secret ALLUXIO_LICENSE_STRING
cat > "$work_dir/cluster.yaml" <<EOF
apiVersion: k8s-operator.alluxio.com/v1
kind: AlluxioCluster
metadata:
  name: alluxio
  namespace: alx-ns
spec:
  image: $alluxio_image
  imageTag: $alluxio_tag
  properties:
    alluxio.worker.s3.api.enabled: "true"
    alluxio.worker.s3.redirect.enabled: "false"
    alluxio.security.authentication.type: SIMPLE
    alluxio.underfs.abfs.sdk.version: "2"
  coordinator:
    nodeSelector: {agentpool: systempool}
    resources:
      requests: {cpu: "4", memory: 12Gi}
      limits: {cpu: "4", memory: 12Gi}
    jvmOptions: ["-Xmx4g", "-Xms4g", "-XX:MaxDirectMemorySize=4g"]
  worker:
    count: 1
    nodeSelector: {agentpool: workerpool}
    tolerations:
      - {key: alluxio, operator: Equal, value: "true", effect: NoSchedule}
    resources:
      requests: {cpu: "8", memory: 24Gi}
      limits: {cpu: "8", memory: 24Gi}
    jvmOptions: ["-Xmx8g", "-Xms8g", "-XX:MaxDirectMemorySize=12g"]
    pagestore: {size: 8Gi, reservedSize: 1Gi}
  # A single etcd replica is sufficient for this disposable, non-HA PoC.
  etcd:
    replicaCount: 1
    nodeSelector: {agentpool: systempool}
    persistence: {storageClass: managed-csi, size: 10Gi}
  prometheus: {enabled: false}
  grafana: {enabled: false}
EOF
timeout 180 kubectl create --dry-run=server --validate=strict -f "$work_dir/cluster.yaml" > /dev/null
timeout 180 kubectl create -f "$work_dir/cluster.yaml" > /dev/null
jq -n '{
    apiVersion: "k8s-operator.alluxio.com/v1", kind: "License",
    metadata: {name: "alluxio-license", namespace: "alx-ns"},
    spec: {clusters: [{name: "alluxio", namespace: "alx-ns"}],
           licenseString: env.ALLUXIO_LICENSE_STRING}
}' > "$work_dir/license.json"
create_private_resource "$work_dir/license.json"
wait_phase license alluxio-license phase Completed
wait_phase alluxiocluster alluxio clusterPhase Ready
for pod in alluxio-coordinator-0 alluxio-worker-0; do
    timeout 660 kubectl wait -n alx-ns --for=condition=Ready "pod/$pod" --timeout=600s
done
"""
        workDir
        resultDir
        "alluxio_cluster"
        environment = {
            alluxio_tag = ALLUXIO_TAG
            ALLUXIO_LICENSE_STRING = "$(ALLUXIO_LICENSE_STRING)"
        }
    )
}

MountBlobStorage = lambda workDir: str, resultDir: str -> steps.Bash {
    BashStep(
        "Mount Azure Blob in Alluxio"
        LOAD_CONFIG + RESOURCE_COMMANDS + REDACT_OUTPUT + """
export BLOB_SAS
BLOB_SAS="$(< "$work_dir/blob-sas")"
jq -n --arg account "$storage_account" '{
    apiVersion: "k8s-operator.alluxio.com/v1", kind: "UnderFileSystem",
    metadata: {name: "alluxio-blob", namespace: "alx-ns"},
    spec: {alluxioCluster: "alluxio", mountPath: "/blob",
           path: ("abfs://" + $account + ".blob.core.windows.net/warp-data/"),
           mountOptions: {"alluxio.underfs.abfs.sas.token": env.BLOB_SAS}}
}' > "$work_dir/ufs.json"
create_private_resource "$work_dir/ufs.json"
wait_phase ufs alluxio-blob phase Ready
timeout 180 kubectl --request-timeout=180s exec -n alx-ns alluxio-coordinator-0 \\
    -c alluxio-coordinator -- alluxio fs ls /blob | redact
"""
        workDir
        resultDir
        "alluxio_mount"
    )
}
