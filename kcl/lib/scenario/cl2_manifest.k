# cl2_manifest.k renders the ClusterLoader2 "driver" manifest from KCL.
#
# The CL2 driver is the in-cluster Job that runs the ClusterLoader2 binary; it
# reads its tunables from a mounted `override.yaml` ConfigMap and generates the
# measured workload pods internally. Historically this manifest was a static
# multi-document YAML file copied per scenario. Modeling it as a typed module
# means a scenario author tunes load via named fields instead of editing raw
# YAML, and enabling a feature like AKS Kata Confidential Containers is a single
# field (`runtimeClassName`) rather than a hand-edited string.
#
# `buildCl2Manifest` returns the manifest as a list of Kubernetes objects. When
# selected with `kcl run cl2.k -S manifests`, KCL serializes the list as a
# multi-document (`---` separated) YAML stream that `kubectl apply -f` accepts
# unchanged, so RunClusterLoader2 needs no changes.

# _boolStr renders a KCL bool as a lowercase YAML boolean literal ("true" /
# "false") for embedding inside the override.yaml text block. (Plain string
# interpolation of a KCL bool would yield "True"/"False", which CL2 rejects.)
_boolStr = lambda v: bool -> str {
    "true" if v else "false"
}

# Cl2Override holds the knobs CL2 reads from override.yaml. Defaults mirror the
# previous static manifest so an unconfigured Cl2Manifest reproduces today's
# behavior.
schema Cl2Override:
    nodes: int = 30
    podsPerNode: int = 10
    bigGroupSize: int = 8
    mediumGroupSize: int = 8
    smallGroupSize: int = 4
    smallStatefulSetsPerNamespace: int = 0
    mediumStatefulSetsPerNamespace: int = 0
    rateLimitPodCreation: bool = False
    enablePvs: bool = False
    enableClusterOomsTracker: bool = False
    defaultQps: int = 5000
    # runOnArmNodes is a hack that lets CL2 schedule onto KWOK fake nodes.
    runOnArmNodes: bool = True
    # runtimeClassName, when set, makes the measured workload pods run under the
    # named RuntimeClass. Set "kata-mshv-vm-isolation" to benchmark AKS Kata
    # Confidential Containers. Unset -> the cluster default runtime (runc).
    runtimeClassName?: str

# Cl2Manifest holds everything needed to render the CL2 driver manifest.
schema Cl2Manifest:
    namespace: str = "clusterloader2"
    # nodePoolName is the pool CL2 is pinned to; it drives both the nodeSelector
    # (agentpool=<name>) and the matching NoSchedule toleration key.
    nodePoolName: str = "cl2pool"
    image: str = "ghcr.io/azure/clusterloader2:v20260220"
    completions: int = 4
    parallelism: int = 4
    k8sClientsNumber: int = 500
    cpuRequest: str = "6"
    memoryRequest: str = "24Gi"
    override: Cl2Override = Cl2Override {}

# buildCl2Manifest renders a Cl2Manifest into the list of Kubernetes objects
# that make up the CL2 driver: an override ConfigMap, the CL2 Job, and the
# ServiceAccount/ClusterRole/ClusterRoleBinding it runs as.
buildCl2Manifest = lambda m: Cl2Manifest -> [{str:any}] {
    o = m.override

    overrideLines = [
        "NODES: ${o.nodes}",
        "PODS_PER_NODE: ${o.podsPerNode}",
        "BIG_GROUP_SIZE: ${o.bigGroupSize}",
        "MEDIUM_GROUP_SIZE: ${o.mediumGroupSize}",
        "SMALL_GROUP_SIZE: ${o.smallGroupSize}",
        "SMALL_STATEFUL_SETS_PER_NAMESPACE: ${o.smallStatefulSetsPerNamespace}",
        "MEDIUM_STATEFUL_SETS_PER_NAMESPACE: ${o.mediumStatefulSetsPerNamespace}",
        "CL2_RATE_LIMIT_POD_CREATION: ${_boolStr(o.rateLimitPodCreation)}",
        "CL2_ENABLE_PVS: ${_boolStr(o.enablePvs)}",
        "CL2_ENABLE_CLUSTER_OOMS_TRACKER: ${_boolStr(o.enableClusterOomsTracker)}",
        "CL2_DEFAULT_QPS: ${o.defaultQps}",
        "CL2_RUN_ON_ARM_NODES: ${_boolStr(o.runOnArmNodes)} # This is a hack to allow Cl2 to run on Kwok nodes",
        "CL2_RUNTIME_CLASS_NAME: ${o.runtimeClassName}" if o.runtimeClassName else "",
    ]
    overrideYaml = "\n".join([line for line in overrideLines if line])

    [
        {
            apiVersion = "v1"
            kind = "ConfigMap"
            metadata = {
                name = "cl2-override"
                namespace = m.namespace
            }
            data = {
                "override.yaml" = overrideYaml
            }
        }
        {
            apiVersion = "batch/v1"
            kind = "Job"
            metadata = {
                name = "cl2"
                namespace = m.namespace
            }
            spec = {
                completions = m.completions
                parallelism = m.parallelism
                backoffLimit = 0
                template.spec = {
                    containers = [
                        {
                            name = "cl2"
                            image = m.image
                            args = [
                                "--provider=aks"
                                "--run-from-cluster=true"
                                "--v=2"
                                "--testoverrides=/override/override.yaml"
                                "--testconfig=testing/load/config.yaml"
                                "--k8s-clients-number=${m.k8sClientsNumber}"
                            ]
                            resources.requests = {
                                cpu = m.cpuRequest
                                memory = m.memoryRequest
                            }
                            volumeMounts = [
                                {
                                    mountPath = "/override"
                                    name = "cl2-override"
                                }
                            ]
                        }
                    ]
                    nodeSelector = {
                        agentpool = m.nodePoolName
                    }
                    restartPolicy = "Never"
                    serviceAccountName = "cl2"
                    tolerations = [
                        {
                            effect = "NoSchedule"
                            key = m.nodePoolName
                            operator = "Exists"
                        }
                    ]
                    volumes = [
                        {
                            name = "cl2-override"
                            configMap.name = "cl2-override"
                        }
                    ]
                }
            }
        }
        {
            apiVersion = "v1"
            kind = "ServiceAccount"
            metadata = {
                name = "cl2"
                namespace = m.namespace
            }
        }
        {
            apiVersion = "rbac.authorization.k8s.io/v1"
            kind = "ClusterRole"
            metadata = {
                name = "cl2"
            }
            rules = [
                {
                    apiGroups = ["*"]
                    resources = ["*"]
                    verbs = ["*"]
                }
            ]
        }
        {
            apiVersion = "rbac.authorization.k8s.io/v1"
            kind = "ClusterRoleBinding"
            metadata = {
                name = "cl2"
            }
            roleRef = {
                apiGroup = "rbac.authorization.k8s.io"
                kind = "ClusterRole"
                name = "cl2"
            }
            subjects = [
                {
                    kind = "ServiceAccount"
                    name = "cl2"
                    namespace = m.namespace
                }
            ]
        }
    ]
}
