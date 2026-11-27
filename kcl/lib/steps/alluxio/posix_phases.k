import azure_pipelines.ap.steps
import lib.const
import lib.steps.azure

# The aks-preview CLI extension carries the Distributed Accelerator Cache Storage (DACS) commands, which
# need version 22.0.0b9 or newer. The version is pinned to one with which enabling DACS has been verified,
# so that a run always uses the same CLI behaviour.
DACS_AKS_PREVIEW_VERSION = "22.0.0b16"

# `az aks update --enable-azure-container-storage distributedAccelerator` also needs the k8s-extension CLI
# extension and fails without it. Version 1.9.5 is the one verified to work with the aks-preview version above.
DACS_K8S_EXTENSION_VERSION = "1.9.5"

# The cache nodes carry this label, which the DACS Cache selects on (nodeSelectorKey and
# nodeSelectorValue in dacs-cache.yaml). Labelling the node pool when it is created is preferable: set
# NodePool.labels to this value for the DACS phase's pool, and the step below only verifies it.
DACS_NODE_LABEL = "dacs.azure.com/processing-unit=cpu"
# The DACS phase's node pool. It must differ from the Alluxio phase's "workerpool": AKS derives the VMSS and node
# names from the pool name, so a new pool of the same name reuses the names of the deleted nodes, and a stale Node
# object that kept the DACS label above would start dacs-prereq (which builds RAID0 on the NVMe disks) on an
# Alluxio node. At most 12 lowercase alphanumerics.
DACS_NODE_POOL = "dacspool"
DACS_NAMESPACE = "dacs-cache-system"

# Polls "$@" every 15 s until it succeeds; fails with a message after <timeout> seconds. Needs the
# fail() of PosixShellSetup.
# Usage: wait_until <timeout seconds> <what is awaited> <command> [args...]
PHASES_WAIT_SHELL = """
wait_until() {
    local timeout="$1" what="$2" deadline
    shift 2
    deadline=$((SECONDS + timeout))
    until "$@"; do
        (( SECONDS < deadline )) || fail "timed out after $timeout s waiting for $what"
        sleep 15
    done
}
"""

# Enables DACS on the cluster, labels the cache nodes, creates the Cache and waits until exactly
# POSIX_CACHE_COUNT servers are Ready. manifest is dacs-cache.yaml; its POSIX_CACHE_COUNT placeholder is
# replaced in a copy under workDir, and the Cache is created (never applied). The versions of the aks-preview and
# k8s-extension CLI extensions, which only this step uses, are written to the result directory.
EnableDacs = lambda subscription: str, resourceGroup: str, cluster: str, manifest: str, workDir: str, resultDir: str, serviceConnection: str = const.DEFAULT_SERVICE_CONNECTION -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Enable DACS and create the cache"
        PosixShellSetup(workDir, resultDir) + PHASES_WAIT_SHELL + """
dacs_prereq_ready() {
    local ds
    ds="$(kubectl get daemonset dacs-prereq -n kube-system -o json)" || return 1
    jq -e --argjson want ${POSIX_CACHE_COUNT} \\
        '.status.desiredNumberScheduled == $want and .status.numberReady == $want' <<< "$ds" > /dev/null
}
dacs_servers_ready() {
    local pods
    pods="$(kubectl get pods -n ${DACS_NAMESPACE} -o json)" || return 1
    jq -e --argjson want ${POSIX_CACHE_COUNT} \\
        '[.items[] | select(.metadata.name | startswith("bench-cache-"))] as $p |
        ($p | length) == $want and
        all($p[]; .status.phase == "Running" and any(.status.conditions[]?; .type == "Ready" and .status == "True"))' \\
        <<< "$pods" > /dev/null
}

# The extensions go into a directory of this step only, so no other step of the job, and no other job on the
# agent, runs az with them (aks-preview replaces commands such as az aks nodepool). The directory starts empty,
# so the pinned versions are the ones that run.
export AZURE_EXTENSION_DIR="$POSIX_WORK/dacs-az-extensions"
rm -rf -- "$AZURE_EXTENSION_DIR"
az extension add \\
    --name aks-preview \\
    --version "${DACS_AKS_PREVIEW_VERSION}" \\
    --yes
az extension add \\
    --name k8s-extension \\
    --version "${DACS_K8S_EXTENSION_VERSION}" \\
    --yes
az aks update \\
    --name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --enable-azure-container-storage distributedAccelerator \\
    --yes
az extension show \\
    --name aks-preview \\
    --query version \\
    --output tsv > "$POSIX_RESULT/dacs-aks-preview-version.txt"
az extension show \\
    --name k8s-extension \\
    --query version \\
    --output tsv > "$POSIX_RESULT/dacs-k8s-extension-version.txt"
az aks show \\
    --name "${cluster}" \\
    --resource-group "${resourceGroup}" \\
    --subscription "${subscription}" \\
    --query storageProfile \\
    --output json > "$POSIX_RESULT/dacs-storage-profile.json"

# Idempotent: nodes that already carry the label from node pool creation are left as they are.
kubectl label nodes \\
    --selector agentpool=${DACS_NODE_POOL} \\
    --overwrite \\
    ${DACS_NODE_LABEL}
labelled="$(kubectl get nodes --selector ${DACS_NODE_LABEL} --no-headers | grep -c . || true)"
[[ "$labelled" == ${POSIX_CACHE_COUNT} ]] || fail "expected ${POSIX_CACHE_COUNT} nodes labelled ${DACS_NODE_LABEL}, found $labelled"

kubectl get namespace ${DACS_NAMESPACE} > /dev/null 2>&1 || kubectl create namespace ${DACS_NAMESPACE}

# The NVMe preparation DaemonSet must be ready on every cache node before the Cache is created. 900 s covers
# pulling its image on fresh nodes and building the RAID0 volume.
wait_until 900 "the dacs-prereq DaemonSet to be ready on ${POSIX_CACHE_COUNT} nodes" dacs_prereq_ready

sed "s|POSIX_CACHE_COUNT|${POSIX_CACHE_COUNT}|" "${manifest}" > "${workDir}/dacs-cache.yaml"
kubectl create -f "${workDir}/dacs-cache.yaml"
# 900 s covers pulling the server image on fresh nodes.
wait_until 900 "exactly ${POSIX_CACHE_COUNT} bench-cache- servers to be Ready" dacs_servers_ready
"""
        timeoutInMinutes = POSIX_STEP_TIMEOUT_MINUTES
    )
}

# Shell functions that read the value of alluxio.fuse.enforce.direct.io.read an Alluxio FUSE pod starts with. The
# operator renders the AlluxioCluster properties into alluxio-site.properties in a ConfigMap that the FUSE pods
# mount; which ConfigMap, container and directory is read from a FUSE pod's spec. In a properties file the last
# line of a key wins. A missing key reads as an empty value, which never matches. Needs fail() of PosixShellSetup.
FUSE_DIRECT_IO_SHELL = """
# Prints the value of the last alluxio.fuse.enforce.direct.io.read line of the properties text on stdin.
direct_io_value() {
    awk '/^[[:space:]]*alluxio\\.fuse\\.enforce\\.direct\\.io\\.read[[:space:]]*=/ { value = $0; sub(/^[^=]*=/, "", value); gsub(/[[:space:]]/, "", value) } END { print value }'
}
# Prints "<ConfigMap><TAB><container><TAB><mount directory>" for the ConfigMap volume of the pod that holds
# alluxio-site.properties.
# Usage: fuse_conf_of <pod>
fuse_conf_of() {
    local spec names name conf
    spec="$(kubectl get pod "$1" -n "$POSIX_NS" -o json)" || fail "could not read the spec of $1"
    names="$(jq -r '.spec.volumes[]? | .configMap.name // empty' <<< "$spec")"
    for name in $names; do
        if kubectl get configmap "$name" -n "$POSIX_NS" -o json | jq -e '.data["alluxio-site.properties"] != null' > /dev/null; then
            conf="$(jq -r --arg configmap "$name" '[.spec.volumes[] | select(.configMap.name == $configmap) | .name] as $volumes
                | [.spec.containers[] | .name as $container | .volumeMounts[]? | select(.name as $volume | any($volumes[]; . == $volume))
                    | [$configmap, $container, .mountPath]] | if length == 0 then empty else .[0] | @tsv end' <<< "$spec")"
            [[ -n "$conf" ]] || fail "no container of $1 mounts the ConfigMap $name"
            echo "$conf"
            return 0
        fi
    done
    fail "no ConfigMap volume of $1 holds alluxio-site.properties"
}
# Succeeds when the ConfigMap holds alluxio.fuse.enforce.direct.io.read=<value>.
# Usage: configmap_has_direct_io <ConfigMap> <value>
configmap_has_direct_io() {
    local configmap
    configmap="$(kubectl get configmap "$1" -n "$POSIX_NS" -o json)" || return 1
    [[ "$(jq -r '.data["alluxio-site.properties"] // ""' <<< "$configmap" | direct_io_value)" == "$2" ]]
}
# Fails unless every FUSE pod has alluxio.fuse.enforce.direct.io.read=<value> in the alluxio-site.properties it
# mounts, the file its FUSE process read when it started.
# Usage: require_fuse_direct_io <value>
require_fuse_direct_io() {
    local pods pod conf configmap container directory value
    pods="$(kubectl get pods -n "$POSIX_NS" -o name)" || fail "could not list the pods in $POSIX_NS"
    pods="$(sed -n 's|^pod/\\(alluxio-fuse-.*\\)$|\\1|p' <<< "$pods")"
    [[ -n "$pods" ]] || fail "no Alluxio FUSE pod to read alluxio.fuse.enforce.direct.io.read from"
    for pod in $pods; do
        conf="$(fuse_conf_of "$pod")"
        IFS=$'\\t' read -r configmap container directory <<< "$conf"
        value="$(timeout 60 kubectl exec -n "$POSIX_NS" "$pod" -c "$container" -- cat "$directory/alluxio-site.properties" | direct_io_value)" ||
            fail "could not read $directory/alluxio-site.properties in $pod"
        [[ "$value" == "$1" ]] || fail "$pod started with alluxio.fuse.enforce.direct.io.read '$value' from the ConfigMap $configmap, not $1"
    done
}
"""

# Shell functions that start the elbencho service pods that read through the Alluxio FUSE mount, and replace
# them. They expect PosixShellSetup, POSIX_RUNTIME_SHELL (client_list) and PHASES_WAIT_SHELL (wait_until) before them.
FUSE_CLIENTS_SHELL = """
# client_list calls fail() (exit) on a wrong count, so it runs in a subshell here.
clients_ready() {
    (client_list) > /dev/null 2>&1
}
# Creates one copy of the manifest (clients-fuse.yaml) per client node, named posix-client-<i>, with ELBENCHO_IMAGE
# replaced by the image, waits for exactly ${POSIX_CLIENT_COUNT} Ready pods and fails unless /data in each is a
# FUSE mount that can be listed: a plain directory there would let the test read an empty or wrong location
# without any error, and a mount whose FUSE process is gone fails every access.
# Usage: start_fuse_clients <manifest> <elbencho image>
start_fuse_clients() {
    local i pods pod fstype
    # The anti-affinity rule in the manifest puts each copy on its own node.
    for i in $(seq 1 ${POSIX_CLIENT_COUNT}); do
        sed -e "s|ELBENCHO_IMAGE|$2|" -e "s|^  name: posix-client$|  name: posix-client-$i|" "$1" |
            kubectl create -f -
    done
    # 600 s covers pulling the elbencho image on every client node.
    wait_until 600 "exactly ${POSIX_CLIENT_COUNT} elbencho service pods to be Ready" clients_ready
    # An assignment keeps a failure of client_pods; in the for-list it would leave the loop with no pod checked.
    pods="$(client_pods)"
    for pod in $pods; do
        fstype="$(timeout 60 kubectl exec -n "$POSIX_NS" "$pod" -- awk '$2 == "/data" { type = $3 } END { print type }' /proc/mounts)"
        [[ "$fstype" == fuse* ]] || fail "$pod: /data is not a FUSE mount (file system type '$fstype')"
        timeout 60 kubectl exec -n "$POSIX_NS" "$pod" -- ls /data > /dev/null || fail "$pod: /data is a FUSE mount that cannot be listed"
    done
}
# Succeeds when exactly ${POSIX_CLIENT_COUNT} FUSE pods exist, all Ready, none of them one of the old pods ($1).
fuse_restarted() {
    local pods
    pods="$(kubectl get pods -n "$POSIX_NS" -o json)" || return 1
    jq -e --argjson old "$1" --argjson want ${POSIX_CLIENT_COUNT} \\
        '[.items[] | select(.metadata.name | startswith("alluxio-fuse-"))] as $p |
        ($p | length) == $want and
        all($p[]; (.metadata.uid as $u | ($old | index($u)) == null) and .status.phase == "Running" and
            any(.status.conditions[]?; .type == "Ready" and .status == "True"))' <<< "$pods" > /dev/null
}
# Deletes the ${POSIX_CLIENT_COUNT} Alluxio FUSE pods and waits until the DaemonSet has replaced each with a Ready pod.
# Usage: restart_fuse_pods
restart_fuse_pods() {
    local fuse_pods old_uids
    fuse_pods="$(kubectl get pods -n "$POSIX_NS" -o json)" || fail "could not list the pods in $POSIX_NS"
    old_uids="$(jq -c '[.items[] | select(.metadata.name | startswith("alluxio-fuse-")) | .metadata.uid]' <<< "$fuse_pods")"
    [[ "$(jq length <<< "$old_uids")" == ${POSIX_CLIENT_COUNT} ]] || fail "expected ${POSIX_CLIENT_COUNT} Alluxio FUSE pods before the restart, found $old_uids"
    kubectl get pods -n "$POSIX_NS" -o name | grep '^pod/alluxio-fuse-' | xargs kubectl delete --ignore-not-found -n "$POSIX_NS" --wait=true --timeout=300s ||
        fail "could not delete the Alluxio FUSE pods within 300 s"
    # A FUSE restart is a pod restart only; 600 s also covers an image pull on a node that lost it.
    wait_until 600 "${POSIX_CLIENT_COUNT} restarted Alluxio FUSE pods to be Ready" fuse_restarted "$old_uids"
}
# Replaces the elbencho service pods. A client pod keeps the FUSE mount of the FUSE process that served the host
# path when the pod started: once that process is gone (a FUSE pod restart), /data in the pod fails with
# "Transport endpoint is not connected" until the pod is created again. 300 s bounds the deletion.
# Usage: recreate_fuse_clients <manifest> <elbencho image>
recreate_fuse_clients() {
    local left
    kubectl delete pod -n "$POSIX_NS" -l ${POSIX_CLIENT_LABEL} --ignore-not-found --wait=true --timeout=300s > /dev/null ||
        fail "could not delete the elbencho service pods within 300 s"
    left="$(kubectl get pods -n "$POSIX_NS" -l ${POSIX_CLIENT_LABEL} -o name)" || fail "could not list the elbencho service pods"
    [[ -z "$left" ]] || fail "elbencho service pods still exist after their deletion: $left"
    start_fuse_clients "$1" "$2"
}
"""

# Shell snippet (it expects PosixShellSetup and POSIX_RUNTIME_SHELL before it) that sets
# alluxio.fuse.enforce.direct.io.read on the AlluxioCluster, restarts the FUSE pods and waits for the new ones.
# The patch is a JSON merge patch, which merges maps, so only this one key changes. The operator renders the
# property into the FUSE pods' ConfigMap but does not roll the pods, so the pods are deleted by hand, and only
# once the ConfigMap holds the new value: a pod started earlier would read the old one. Afterwards every new FUSE
# pod must have the new value in the file it read. The restart leaves the elbencho service pods with a dead FUSE
# mount, so they are then recreated from clientsManifest (clients-fuse.yaml) with elbenchoImage (see
# recreate_fuse_clients); a step must not list /data or run elbencho in between.
SetAlluxioDirectIo = lambda enabled: bool, clientsManifest: str, elbenchoImage: str -> str {
    assert clientsManifest != "" and elbenchoImage != "", "the FUSE restart recreates the elbencho pods and needs their manifest and image"
    value = "true" if enabled else "false"
    PHASES_WAIT_SHELL + FUSE_DIRECT_IO_SHELL + FUSE_CLIENTS_SHELL + """
fuse_pods="$(kubectl get pods -n "$POSIX_NS" -o json)" || fail "could not list the pods in $POSIX_NS"
first_fuse="$(jq -r '[.items[] | select(.metadata.name | startswith("alluxio-fuse-")) | .metadata.name] | sort | .[0]' <<< "$fuse_pods")"
fuse_configmap="$(fuse_conf_of "$first_fuse" | cut -f1)"
kubectl patch alluxiocluster alluxio -n "$POSIX_NS" --type merge \\
    --patch '{"spec":{"properties":{"alluxio.fuse.enforce.direct.io.read":"${value}"}}}'
[[ "$(kubectl get alluxiocluster alluxio -n "$POSIX_NS" -o jsonpath='{.spec.properties.alluxio\\.fuse\\.enforce\\.direct\\.io\\.read}')" == ${value} ]] ||
    fail "alluxio.fuse.enforce.direct.io.read was not set to ${value}"
# The operator renders the change within seconds; 300 s bounds a stuck reconciliation.
wait_until 300 "the ConfigMap $fuse_configmap to hold alluxio.fuse.enforce.direct.io.read=${value}" configmap_has_direct_io "$fuse_configmap" ${value}
restart_fuse_pods
require_fuse_direct_io ${value}
recreate_fuse_clients "${clientsManifest}" "${elbenchoImage}"
"""
}

# Restarts the Alluxio FUSE pods (restart_fuse_pods), then creates the elbencho service pods that read through
# the Alluxio FUSE mount: one copy of manifest
# (clients-fuse.yaml) per client node, named posix-client-<i>, with ELBENCHO_IMAGE replaced by elbenchoImage.
# Waits for exactly POSIX_CLIENT_COUNT Ready pods and fails unless /data in each is a FUSE mount that can be
# listed (start_fuse_clients).
PrepareAlluxioFuseClients = lambda manifest: str, elbenchoImage: str, workDir: str, resultDir: str, serviceConnection: str = const.DEFAULT_SERVICE_CONNECTION -> steps.Step {
    azure.AzCli(
        serviceConnection
        "Start the elbencho pods on the Alluxio FUSE mount"
        PosixShellSetup(workDir, resultDir) + POSIX_RUNTIME_SHELL + PHASES_WAIT_SHELL + FUSE_CLIENTS_SHELL + """
# The FUSE pods started with the cluster, before /posix was mounted, and each learns of the new mount point from
# etcd a few seconds after it is added. A lookup of the FUSE root (/posix) in that window, such as the kubelet's
# check of the client pods' host path, can keep failing with "No such file or directory" afterwards (seen for more
# than 10 minutes; client metadata is cached for alluxio.user.metadata.cache.expiration.time, 1 h). Restarted
# pods start with /posix in the mount table.
restart_fuse_pods
start_fuse_clients "${manifest}" "${elbenchoImage}"
"""
        stepName = "alluxio_fuse_clients"
    )
}
