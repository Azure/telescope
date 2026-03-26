# Pipeline Trace: `new-pipeline-test.yml`

> Full code-path trace from root pipeline to every leaf file, with analysis of what is **core** to the SwiftV2 scale test vs. **unnecessary fluff** from the generic Telescope framework.

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [Complete Call Graph](#2-complete-call-graph)
3. [File Inventory (All Files Touched)](#3-file-inventory)
4. [Detailed Flow per Stage](#4-detailed-flow-per-stage)
5. [Core Purpose Analysis](#5-core-purpose-analysis)
6. [Unnecessary Steps & Files](#6-unnecessary-steps--files)
7. [Files that Could Be Removed in a Standalone Rewrite](#7-files-that-could-be-removed)

---

## 1. Pipeline Overview

**File:** `pipelines/system/new-pipeline-test.yml`

This pipeline benchmarks **Azure SwiftV2 (Pod Network Instance)** networking at scale. At its core, it:

1. Creates/reuses an AKS cluster with SwiftV2 networking
2. Scales user nodepools to target sizes (500 → 2000 nodes)
3. Runs ClusterLoader2 (CL2) to deploy pods with PNIs and measure pod startup latency
4. Uses the **datapath-observer** (controller + reporter) to measure time-to-start and time-to-datapath-ready
5. Collects results and uploads them to Azure Blob Storage

The pipeline has **4 stages**, but only 2 are active (`condition: false` on the burst stages):

| Stage | Active | Description |
|-------|--------|-------------|
| `staticres_gradual` | **Yes** | Static PNI resources, gradual pod scaling (50/step) |
| `dynamicres_gradual` | **Yes** | Dynamic PNI resources, gradual pod scaling (50/step) |
| `staticres_burst` | No | Static PNI resources, burst pod scaling (all-at-once) |
| `dynamicres_burst` | No | Dynamic PNI resources, burst pod scaling (all-at-once) |

Each active stage runs a **matrix** of 4 scale points: 500, 1000, 1500, 2000 nodes (sequentially, `max_parallel: 1`).

---

## 2. Complete Call Graph

```
pipelines/system/new-pipeline-test.yml
│
├── steps/generate-run-id.yml                          # Generates BASE_RUN_ID (initials-timestamp-prefix)
│
├── pipelines/system/matrices/swiftv2-staticres-gradual-matrix.yml
│   └── jobs/competitive-test.yml                      # Core job orchestrator
│       ├── steps/setup-tests.yml                      # [SETUP]
│       │   ├── (inline) Set Run ID
│       │   ├── (inline) Set Run URL & Code URL
│       │   ├── (inline) Set Test Results Directory
│       │   ├── (inline) Check Dependencies
│       │   ├── (inline) Install Dependencies           # pip install requirements.txt
│       │   ├── steps/cloud/azure/login.yml            # Azure CLI login (SP or MI)
│       │   └── (inline) Set Script Module Directory
│       │
│       ├── steps/provision-resources.yml               # [PROVISION]
│       │   ├── (inline) Set Resource Group Name
│       │   ├── (inline) Get Deletion Due Time and Owner
│       │   ├── (inline) Ensure Resource Group           # az group create
│       │   ├── (inline) SetupCustomerResources          # ⚠ conditional: CREATE_CUSTOMER_RESOURCES
│       │   │   └── swiftv2kubeobjects/runCustomerSetup.sh
│       │   │       └── swiftv2kubeobjects/shared-config.sh
│       │   ├── (inline) Ensure AKS Cluster              # ✅ CORE
│       │   │   └── swiftv2kubeobjects/createclusterforping.sh
│       │   │       ├── swiftv2kubeobjects/shared-config.sh
│       │   │       ├── swiftv2kubeobjects/lib/common.sh
│       │   │       └── swiftv2kubeobjects/lib/nodepool.sh
│       │   └── (inline) EnsureUserNodepools              # ✅ CORE
│       │       └── swiftv2kubeobjects/ensure-nodepools.sh
│       │           ├── swiftv2kubeobjects/shared-config.sh
│       │           ├── swiftv2kubeobjects/lib/nodepool.sh
│       │           │   └── swiftv2kubeobjects/lib/common.sh
│       │           └── steps/engine/clusterloader2/swiftv2-slo/aks-utils.sh
│       │               └── swiftv2kubeobjects/lib/common.sh
│       │
│       ├── steps/validate-resources.yml                # [VALIDATE]
│       │   ├── (inline) Validate OWNER info             # ⚠ Only when SKIP_RESOURCE_MANAGEMENT=true
│       │   └── steps/topology/swiftv2/validate-resources.yml
│       │       ├── steps/cloud/azure/update-kubeconfig.yml   # az aks get-credentials
│       │       ├── steps/engine/clusterloader2/swiftv2-slo/scale-cluster.yml
│       │       │   └── steps/engine/clusterloader2/swiftv2-slo/scale-cluster.sh  # ✅ CORE: scale nodepools
│       │       │       └── steps/engine/clusterloader2/swiftv2-slo/aks-utils.sh
│       │       ├── steps/engine/clusterloader2/swiftv2-slo/prepull-images.yml
│       │       │   └── steps/engine/clusterloader2/swiftv2-slo/prepull-images.sh  # ✅ CORE: DaemonSet image pre-pull
│       │       │       ├── steps/engine/clusterloader2/swiftv2-slo/aks-utils.sh
│       │       │       └── steps/engine/clusterloader2/swiftv2-slo/prepull-daemonset-template.yaml
│       │       └── steps/engine/clusterloader2/swiftv2-slo/validate.yml
│       │           └── modules/python/clusterloader2/swiftv2-slo/slo.py validate  # ✅ CORE
│       │               └── modules/python/clients/kubernetes_client.py
│       │
│       ├── steps/execute-tests.yml                     # [EXECUTE]
│       │   └── steps/topology/swiftv2/execute-clusterloader2.yml
│       │       └── steps/engine/clusterloader2/swiftv2-slo/execute.yml
│       │           └── modules/python/clusterloader2/swiftv2-slo/slo.py configure + execute  # ✅ CORE
│       │               ├── modules/python/clusterloader2/utils.py    # run_cl2_command via Docker
│       │               │   └── modules/python/clients/docker_client.py
│       │               └── CL2 Config Files (in modules/python/clusterloader2/swiftv2-slo/config/):
│       │                   ├── swiftv2_deployment_staticres_scale_config.yaml  # CL2 test definition (static)
│       │                   ├── swiftv2_deployment_dynamicres_scale_config.yaml # CL2 test definition (dynamic)
│       │                   ├── overrides.yaml                                 # Generated CL2 overrides
│       │                   ├── swiftv2_deployment_single_pod_template.yaml     # Pod template (static: 1 dep = 1 pod)
│       │                   ├── swiftv2_deployment_template.yaml               # Pod template (dynamic: 1 dep = N pods)
│       │                   ├── pni_static_template.yaml                       # PNI CRD (static)
│       │                   ├── pni_dynamic_template.yaml                      # PNI CRD (dynamic)
│       │                   ├── pni_readiness_checker_unified_template.yaml     # PNI readiness checker pod
│       │                   ├── reporter_rbac_template.yaml                    # ServiceAccount for reporter
│       │                   ├── reporter_role_template.yaml                    # Role for pod get/patch
│       │                   └── reporter_rolebinding_template.yaml             # RoleBinding
│       │
│       └── steps/publish-results.yml                   # [PUBLISH]
│           ├── steps/topology/swiftv2/collect-clusterloader2.yml
│           │   ├── steps/engine/clusterloader2/swiftv2-slo/collect.yml
│           │   │   ├── steps/cloud/azure/collect-cloud-info.yml  # Collect AKS metadata
│           │   │   └── modules/python/clusterloader2/swiftv2-slo/slo.py collect  # ✅ CORE: Parse CL2 results
│           │   └── steps/topology/swiftv2/collect-datapath-observer.yml  # ✅ CORE: Query datapath-controller API
│           │
│           ├── steps/collect-telescope-metadata.yml     # ⚠ FRAMEWORK: Build metadata JSON
│           │   └── steps/cloud/azure/upload-storage-account.yml (conditional: main branch only)
│           │
│           └── steps/cloud/azure/upload-storage-account.yml  # ✅ CORE: Upload results.json to blob
│               └── steps/cloud/azure/login.yml (re-auth)
│
├── pipelines/system/matrices/swiftv2-dynamicres-gradual-matrix.yml
│   └── (same as above, different CL2 config: swiftv2_deployment_dynamicres_scale_config.yaml)
│
├── pipelines/system/matrices/swiftv2-staticres-burst-matrix.yml      # condition: false (DISABLED)
├── pipelines/system/matrices/swiftv2-dynamicres-burst-matrix.yml     # condition: false (DISABLED)
│
└── jobs/cleanup.yml                                    # [CLEANUP] (per stage)
    └── steps/cleanup-resources.yml
        ├── (inline) Delete SAL Ping                     # ⚠ conditional: CREATE_CUSTOMER_RESOURCES
        ├── (inline) Cleanup Swiftv2 Workloads           # conditional: SLOW_DELETE=true
        │   └── swiftv2kubeobjects/cleanup-swiftv2-workloads.sh
        │       ├── swiftv2kubeobjects/lib/common.sh
        │       └── swiftv2kubeobjects/shared-config.sh
        ├── (inline) Force Cleanup Azure Resources
        │   └── swiftv2kubeobjects/cleanup-azure-resources.sh
        │       └── swiftv2kubeobjects/lib/common.sh
        └── (inline) Destroy Resource Group              # az group delete
```

### Datapath Observer (Deployed to cluster before test, queried after)

The datapath-observer is **not deployed by this pipeline** — it must be pre-deployed on the AKS cluster. It consists of:

```
swiftv2kubeobjects/datapath-observer/
├── controller/                          # K8s controller (Deployment in perf-ns)
│   ├── main.go                          # Controller-runtime manager + API server
│   ├── controllers/pod_controller.go    # Watches pods, creates DatapathResult CRDs
│   ├── api/v1/datapathresult_types.go   # CRD type definition
│   ├── pkg/server/server.go             # HTTP API: /api/v1/time-to-start, time-to-datapath-ready, pod-health
│   ├── pkg/metrics/metrics.go           # Aggregation: p50/p90/p99 calculations
│   └── manifests/
│       ├── crd.yaml                     # DatapathResult CRD definition
│       ├── deployment.yaml              # Controller deployment (acndev.azurecr.io/datapath-controller)
│       └── rbac.yaml                    # ClusterRole/ServiceAccount
└── reporter/                            # Init container in every test pod
    ├── main.go                          # Probes target URL, patches pod annotations with timestamps
    └── manifests/
        ├── deployment.yaml
        └── rbac.yaml
```

**How it works:**
1. Each test pod has `datapath-reporter` as an **initContainer** — it probes a target URL and records `start-ts` and `dp-ready-ts` as pod annotations
2. The `datapath-controller` watches pods, reads annotations, creates `DatapathResult` CRDs with latency metrics
3. After the CL2 test, the pipeline port-forwards to the controller's API (`:8082`) and queries aggregated metrics
4. Results are merged into the main `results.json` file

---

## 3. File Inventory

### All files touched by this pipeline (68 files):

#### Pipeline Definition (5 files)
| File | Purpose |
|------|---------|
| `pipelines/system/new-pipeline-test.yml` | Root pipeline |
| `pipelines/system/matrices/swiftv2-staticres-gradual-matrix.yml` | Static gradual matrix (500-2000 nodes) |
| `pipelines/system/matrices/swiftv2-dynamicres-gradual-matrix.yml` | Dynamic gradual matrix |
| `pipelines/system/matrices/swiftv2-staticres-burst-matrix.yml` | Static burst matrix (**disabled**) |
| `pipelines/system/matrices/swiftv2-dynamicres-burst-matrix.yml` | Dynamic burst matrix (**disabled**) |

#### Job Templates (2 files)
| File | Purpose |
|------|---------|
| `jobs/competitive-test.yml` | Generic job orchestrator (shared across all topologies) |
| `jobs/cleanup.yml` | Cleanup job template |

#### Step Templates - Generic Framework (8 files)
| File | Purpose |
|------|---------|
| `steps/generate-run-id.yml` | Generate unique run ID |
| `steps/setup-tests.yml` | Generic test setup (run ID, URLs, dependencies, login) |
| `steps/provision-resources.yml` | Generic resource provisioning (RG creation + SwiftV2-specific cluster/nodepool) |
| `steps/validate-resources.yml` | Routing to topology-specific validation |
| `steps/execute-tests.yml` | Routing to topology-specific execution |
| `steps/publish-results.yml` | Routing to topology-specific collection + upload |
| `steps/collect-telescope-metadata.yml` | Build Telescope metadata JSON |
| `steps/cleanup-resources.yml` | Multi-step Azure cleanup |

#### Step Templates - Cloud/Azure (4 files)
| File | Purpose |
|------|---------|
| `steps/cloud/azure/login.yml` | Azure CLI login (SP or MI) |
| `steps/cloud/azure/update-kubeconfig.yml` | Get AKS credentials |
| `steps/cloud/azure/collect-cloud-info.yml` | Collect AKS cluster metadata |
| `steps/cloud/azure/upload-storage-account.yml` | Upload blob to Azure Storage |

#### Step Templates - Topology/SwiftV2 (4 files)
| File | Purpose |
|------|---------|
| `steps/topology/swiftv2/validate-resources.yml` | SwiftV2 validation orchestrator |
| `steps/topology/swiftv2/execute-clusterloader2.yml` | SwiftV2 CL2 execution orchestrator |
| `steps/topology/swiftv2/collect-clusterloader2.yml` | SwiftV2 collection orchestrator |
| `steps/topology/swiftv2/collect-datapath-observer.yml` | Query datapath-controller API |

#### Step Templates - Engine/CL2/SwiftV2-SLO (8 files)
| File | Purpose |
|------|---------|
| `steps/engine/clusterloader2/swiftv2-slo/scale-cluster.yml` | Scale cluster step |
| `steps/engine/clusterloader2/swiftv2-slo/scale-cluster.sh` | Scale nodepools + VM repair |
| `steps/engine/clusterloader2/swiftv2-slo/aks-utils.sh` | AKS utility functions |
| `steps/engine/clusterloader2/swiftv2-slo/prepull-images.yml` | Image pre-pull step |
| `steps/engine/clusterloader2/swiftv2-slo/prepull-images.sh` | DaemonSet-based image pre-pull |
| `steps/engine/clusterloader2/swiftv2-slo/prepull-daemonset-template.yaml` | DaemonSet manifest template |
| `steps/engine/clusterloader2/swiftv2-slo/validate.yml` | Node count validation step |
| `steps/engine/clusterloader2/swiftv2-slo/execute.yml` | CL2 execution step |
| `steps/engine/clusterloader2/swiftv2-slo/collect.yml` | CL2 result collection step |

#### SwiftV2 Shell Scripts (7 files)
| File | Purpose |
|------|---------|
| `swiftv2kubeobjects/createclusterforping.sh` | Create AKS cluster with SwiftV2 networking |
| `swiftv2kubeobjects/ensure-nodepools.sh` | Create/verify user nodepools |
| `swiftv2kubeobjects/cleanup-swiftv2-workloads.sh` | Graceful workload cleanup |
| `swiftv2kubeobjects/cleanup-azure-resources.sh` | Force Azure resource cleanup |
| `swiftv2kubeobjects/shared-config.sh` | Shared subscription/VNet config |
| `swiftv2kubeobjects/lib/common.sh` | Cancellation handling + retry logic |
| `swiftv2kubeobjects/lib/nodepool.sh` | Nodepool create/verify helpers |
| `swiftv2kubeobjects/runCustomerSetup.sh` | One-time customer resource setup (VNet, subnets, identities) |

#### Python Modules (6 files)
| File | Purpose |
|------|---------|
| `modules/python/requirements.txt` | Python dependencies (docker, kubernetes, pylint, coverage) |
| `modules/python/clusterloader2/swiftv2-slo/slo.py` | Main Python orchestrator (configure/validate/execute/collect) |
| `modules/python/clusterloader2/utils.py` | CL2 Docker runner + result parser |
| `modules/python/clients/docker_client.py` | Docker SDK wrapper |
| `modules/python/clients/kubernetes_client.py` | Kubernetes SDK wrapper |
| `modules/python/clusterloader2/__init__.py` | Package init |

#### CL2 Config Templates (11 files)
| File | Purpose |
|------|---------|
| `modules/python/clusterloader2/swiftv2-slo/config/swiftv2_deployment_staticres_scale_config.yaml` | CL2 test config for static PNIs |
| `modules/python/clusterloader2/swiftv2-slo/config/swiftv2_deployment_dynamicres_scale_config.yaml` | CL2 test config for dynamic PNIs |
| `modules/python/clusterloader2/swiftv2-slo/config/overrides.yaml` | Generated CL2 override file (written by slo.py) |
| `modules/python/clusterloader2/swiftv2-slo/config/swiftv2_deployment_single_pod_template.yaml` | Static: 1 deployment = 1 pod |
| `modules/python/clusterloader2/swiftv2-slo/config/swiftv2_deployment_template.yaml` | Dynamic: 1 deployment = N pods |
| `modules/python/clusterloader2/swiftv2-slo/config/pni_static_template.yaml` | Static PNI CRD |
| `modules/python/clusterloader2/swiftv2-slo/config/pni_dynamic_template.yaml` | Dynamic PNI CRD |
| `modules/python/clusterloader2/swiftv2-slo/config/pni_readiness_checker_unified_template.yaml` | PNI readiness checker pod |
| `modules/python/clusterloader2/swiftv2-slo/config/reporter_rbac_template.yaml` | ServiceAccount |
| `modules/python/clusterloader2/swiftv2-slo/config/reporter_role_template.yaml` | Role (pods get/patch) |
| `modules/python/clusterloader2/swiftv2-slo/config/reporter_rolebinding_template.yaml` | RoleBinding |

#### Datapath Observer (13 files)
| File | Purpose |
|------|---------|
| `swiftv2kubeobjects/datapath-observer/controller/main.go` | Controller entry point |
| `swiftv2kubeobjects/datapath-observer/controller/controllers/pod_controller.go` | Pod reconciler |
| `swiftv2kubeobjects/datapath-observer/controller/api/v1/datapathresult_types.go` | CRD types |
| `swiftv2kubeobjects/datapath-observer/controller/api/v1/groupversion_info.go` | GVK registration |
| `swiftv2kubeobjects/datapath-observer/controller/api/v1/zz_generated.deepcopy.go` | Generated deepcopy |
| `swiftv2kubeobjects/datapath-observer/controller/pkg/server/server.go` | HTTP API server |
| `swiftv2kubeobjects/datapath-observer/controller/pkg/metrics/metrics.go` | Metrics aggregation |
| `swiftv2kubeobjects/datapath-observer/controller/manifests/crd.yaml` | CRD manifest |
| `swiftv2kubeobjects/datapath-observer/controller/manifests/deployment.yaml` | Controller deployment |
| `swiftv2kubeobjects/datapath-observer/controller/manifests/rbac.yaml` | Controller RBAC |
| `swiftv2kubeobjects/datapath-observer/controller/Dockerfile` | Controller image |
| `swiftv2kubeobjects/datapath-observer/reporter/main.go` | Reporter init container |
| `swiftv2kubeobjects/datapath-observer/reporter/Dockerfile` | Reporter image |

---

## 4. Detailed Flow per Stage

### Stage: `staticres_gradual` (and `dynamicres_gradual` — identical structure)

#### Job 1: `generate_run_id`
Simple inline step that creates a `BASE_RUN_ID` like `JD-26140530-sg` (initials-timestamp-prefix).

#### Job 2: Matrix job (via `competitive-test.yml`)
Runs sequentially through 4 scale points. For each:

**Phase 1 — Setup** (`setup-tests.yml`):
- Derives unique `RUN_ID` from `BASE_RUN_ID` + job suffix
- Creates test results directory
- Checks Python/jq dependencies
- Installs pip requirements
- Logs into Azure via service connection (gets SP credentials, then `az login`)

**Phase 2 — Provision** (`provision-resources.yml`):
- Sets `RESOURCE_GROUP_NAME` = `BASE_RUN_ID`
- Creates Azure resource group with tags
- **Ensure AKS Cluster**: Runs `createclusterforping.sh` which:
  - Creates VNet with node/pod subnets
  - Creates NAT Gateway
  - Registers VNet with subnet delegator
  - Creates AKS cluster (`az aks create`) with SwiftV2 settings, managed identity, shared kubelet identity for ACR access
- **Ensure User Nodepools**: Runs `ensure-nodepools.sh` which:
  - Calculates number of nodepools needed (shards of 500 nodes)
  - Creates each nodepool with `az aks nodepool add`
  - Labels and taints nodes for SwiftV2

**Phase 3 — Validate** (`validate-resources.yml` → `swiftv2/validate-resources.yml`):
- Gets AKS credentials (`az aks get-credentials`)
- **Scale Cluster**: `scale-cluster.sh` scales nodepools to target `NODE_COUNT`, with retry/VM repair
- **Pre-pull Images**: `prepull-images.sh` creates DaemonSets on labeled nodes to pre-pull `datapath-reporter` and `nginx` images
- **Validate Node Count**: Python `slo.py validate` polls until `NODE_COUNT` nodes are Ready

**Phase 4 — Execute** (`execute-tests.yml` → `swiftv2/execute-clusterloader2.yml`):
- Records start timestamp
- Queries existing pod count (for incremental scaling)
- Python `slo.py configure` writes `overrides.yaml` with all CL2 parameters
- Python `slo.py execute` runs CL2 via Docker container:
  - CL2 processes the config file (`swiftv2_deployment_staticres_scale_config.yaml` or `dynamicres`)
  - CL2 creates PNIs → waits for readiness → creates Deployments → measures pod startup latency
  - Each pod has `datapath-reporter` initContainer that probes target URL and patches annotations

**Phase 5 — Publish** (`publish-results.yml`):
- **Collect CL2 Results**: `slo.py collect` parses `junit.xml` and measurement files from CL2
- **Collect Datapath Results**: Port-forwards to `datapath-controller:8082`, queries:
  - `/api/v1/time-to-start` → p50/p90/p99 pod start latency
  - `/api/v1/time-to-datapath-ready` → p50/p90/p99 datapath ready latency
  - `/api/v1/pod-health` → running/pending/failed counts
  - Merges into `results.json`
- **Collect Telescope Metadata**: Builds metadata JSON (run info, pipeline info, scenario info, cloud info)
- **Upload**: `az storage blob upload` to `telescopedata` storage account under `perf-eval/swiftv2scale/`

#### Job 3: Cleanup (`cleanup.yml`)
- Runs `always()` when `CLEANUP=true`
- Optionally runs `cleanup-swiftv2-workloads.sh` (when `SLOW_DELETE=true`)
- Runs `cleanup-azure-resources.sh` (deletes AKS clusters, NAT gateways, NSGs, public IPs)
- Deletes resource group

---

## 5. Core Purpose Analysis

### What this pipeline ACTUALLY does (the "core"):

1. **Create/reuse AKS cluster** with SwiftV2 networking (VNet, PNI support, subnet delegation)
2. **Scale nodepools** to target size (500-2000 nodes)
3. **Pre-pull container images** on all nodes via DaemonSets
4. **Run CL2 with SwiftV2 config** that:
   - Creates PodNetworkInstances (CRDs)
   - Waits for PNI readiness
   - Creates Deployments with datapath-reporter initContainer
   - Measures PodStartupLatency
5. **Collect datapath metrics** from datapath-controller API (time-to-start, time-to-datapath-ready, pod-health)
6. **Upload results** to Azure Blob Storage
7. **Cleanup** resource group

### What is framework overhead ("fluff"):

The generic Telescope framework adds layers of indirection for multi-cloud (AWS/GCP/Azure), multi-topology (SLO/CRI/CSI/SwiftV2/etc.), multi-engine (CL2/kperf/fio) support. For this specific SwiftV2 test, much of this is unnecessary.

---

## 6. Unnecessary Steps & Files

### Steps that are unnecessary for a standalone SwiftV2 test:

| Step | Why Unnecessary |
|------|-----------------|
| `steps/validate-resources.yml` → OWNER validation | Only matters when `SKIP_RESOURCE_MANAGEMENT=true` (not used here) |
| `steps/collect-telescope-metadata.yml` | Generic metadata for cross-pipeline analytics. A standalone test would just inline the metadata it needs directly into results |
| `steps/setup-tests.yml` → Set Script Module Directory | Sets `TEST_MODULES_DIR` for bash module scripts, but SwiftV2 test doesn't use bash modules |
| `steps/setup-tests.yml` → SSH key setup | `ssh_key_enabled: false` in this pipeline, but the conditional template reference is still present |
| `steps/cloud/azure/collect-cloud-info.yml` | Collects AKS metadata for generic result format. Could be simplified to 2-3 lines |
| `steps/cleanup-resources.yml` → Delete SAL Ping | Only runs when `CREATE_CUSTOMER_RESOURCES=true` (not set in this pipeline) |
| Multi-cloud login abstraction | `steps/cloud/azure/login.yml` has managed_identity + service_connection paths. Only SP is used here |
| Managed Identity login path | Dead code for this pipeline (uses `service_connection`) |
| Generic routing templates | `execute-tests.yml`, `validate-resources.yml`, `publish-results.yml` are 3-line routing files that delegate to topology-specific files |

### Variables that are unused/irrelevant:
- `SKIP_RESOURCE_MANAGEMENT` — always "false"
- `PROVISION_BUFFER_NODES` — always "false"
- `CREATE_CUSTOMER_RESOURCES` — not set (so always false)
- `cilium_enabled`, `scrape_containerd`, `service_test` — all False
- `SLOW_DELETE` — "false"

---

## 7. Files That Could Be Removed in a Standalone Rewrite

If this pipeline were extracted into a self-contained SwiftV2 benchmark without the Telescope framework:

### ❌ REMOVE — Generic Framework Files (not needed)

These files exist to support multi-cloud, multi-topology, multi-engine routing:

```
# Generic job orchestrator (replaced by inline job definition)
jobs/competitive-test.yml

# Generic routing step templates (replaced by direct calls)
steps/validate-resources.yml
steps/execute-tests.yml
steps/publish-results.yml

# Topology routing layers (the swiftv2/ files would be inlined)
steps/topology/swiftv2/validate-resources.yml
steps/topology/swiftv2/execute-clusterloader2.yml
steps/topology/swiftv2/collect-clusterloader2.yml

# Telescope metadata (not needed for standalone)
steps/collect-telescope-metadata.yml

# SSH key setup (not used)
steps/ssh/setup-key.yml

# Other cloud providers (not used)
steps/cloud/aws/                    # (entire directory)
steps/cloud/gcp/                    # (entire directory)

# Other topologies (not used)
steps/topology/cilium-usercluster/
steps/topology/cilium-usercluster-autoscale/
steps/topology/cluster-autoscaler/
steps/topology/cri-autoscale-resource-consume/
steps/topology/cri-kbench-cp/
steps/topology/cri-resource-consume/
steps/topology/csi-attach-detach/
steps/topology/k8s-os-disk/
steps/topology/karpenter/
steps/topology/kperf/
steps/topology/network-load/
steps/topology/network-policy-scale/
steps/topology/service-churn/
steps/topology/slo/

# Other engines (not used)
steps/engine/attach/
steps/engine/fio/
steps/engine/kperf/
steps/engine/clusterloader2/autoscale/
steps/engine/clusterloader2/cilium/
steps/engine/clusterloader2/cri/
steps/engine/clusterloader2/network-load/
steps/engine/clusterloader2/network-policy-scale/
steps/engine/clusterloader2/slo/

# Other CL2 Python modules (not used)
modules/python/clusterloader2/autoscale/
modules/python/clusterloader2/cri/
modules/python/clusterloader2/slo/
modules/python/clusterloader2/docs/

# Other Python modules (not used for SwiftV2)
modules/python/csi/
modules/python/fio/
modules/python/kusto/
modules/python/terraform/
modules/python/tests/
modules/python/utils/

# Terraform modules (not used — cluster created via az CLI)
modules/terraform/                  # (entire directory)

# Terraform step templates
steps/terraform/

# Other matrix files (not used)
# None — all 4 matrix files are SwiftV2-specific

# Disabled burst matrix content (could remove if burst tests not wanted)
pipelines/system/matrices/swiftv2-staticres-burst-matrix.yml
pipelines/system/matrices/swiftv2-dynamicres-burst-matrix.yml

# Other pipeline definitions
pipelines/perf-eval/                # (entire directory)

# Other scenarios
scenarios/                          # (entire directory)

# Other SwiftV2 scripts not invoked by this pipeline
swiftv2kubeobjects/deleteCustomerSetup.sh
swiftv2kubeobjects/nginx-deployment.yaml
swiftv2kubeobjects/pn.yaml
swiftv2kubeobjects/container-insights-syslog-config.yaml
```

### ✅ KEEP — Essential Files for Standalone Rewrite

These are the files that contain actual logic needed by this pipeline:

```
# Pipeline definition (would be simplified)
pipelines/system/new-pipeline-test.yml
pipelines/system/matrices/swiftv2-staticres-gradual-matrix.yml
pipelines/system/matrices/swiftv2-dynamicres-gradual-matrix.yml

# Core step templates
steps/generate-run-id.yml
steps/setup-tests.yml                  # (simplified — remove SSH, module dir)
steps/provision-resources.yml          # (simplified — keep cluster+nodepool logic)
steps/cloud/azure/login.yml           # (simplified — SP path only)
steps/cloud/azure/update-kubeconfig.yml
steps/cloud/azure/collect-cloud-info.yml
steps/cloud/azure/upload-storage-account.yml

# SwiftV2 engine steps (core scale test logic)
steps/engine/clusterloader2/swiftv2-slo/scale-cluster.yml
steps/engine/clusterloader2/swiftv2-slo/scale-cluster.sh
steps/engine/clusterloader2/swiftv2-slo/aks-utils.sh
steps/engine/clusterloader2/swiftv2-slo/prepull-images.yml
steps/engine/clusterloader2/swiftv2-slo/prepull-images.sh
steps/engine/clusterloader2/swiftv2-slo/prepull-daemonset-template.yaml
steps/engine/clusterloader2/swiftv2-slo/validate.yml
steps/engine/clusterloader2/swiftv2-slo/execute.yml
steps/engine/clusterloader2/swiftv2-slo/collect.yml

# Datapath observer collection
steps/topology/swiftv2/collect-datapath-observer.yml

# Cleanup
jobs/cleanup.yml
steps/cleanup-resources.yml

# SwiftV2 infrastructure scripts
swiftv2kubeobjects/createclusterforping.sh
swiftv2kubeobjects/ensure-nodepools.sh
swiftv2kubeobjects/cleanup-swiftv2-workloads.sh
swiftv2kubeobjects/cleanup-azure-resources.sh
swiftv2kubeobjects/shared-config.sh
swiftv2kubeobjects/runCustomerSetup.sh       # (one-time setup, not per-run)
swiftv2kubeobjects/lib/common.sh
swiftv2kubeobjects/lib/nodepool.sh

# Python modules
modules/python/requirements.txt
modules/python/clusterloader2/__init__.py
modules/python/clusterloader2/swiftv2-slo/slo.py
modules/python/clusterloader2/swiftv2-slo/__init__.py
modules/python/clusterloader2/utils.py
modules/python/clients/__init__.py
modules/python/clients/docker_client.py
modules/python/clients/kubernetes_client.py

# CL2 config templates (all needed)
modules/python/clusterloader2/swiftv2-slo/config/  # (entire directory)

# Datapath observer (pre-deployed, not changed per run)
swiftv2kubeobjects/datapath-observer/              # (entire directory — keep for reference/rebuild)
```

### Summary

| Category | Files Used | Files Removable |
|----------|-----------|-----------------|
| Pipeline definition | 5 | 0 (2 disabled but SwiftV2-specific) |
| Generic framework routing | 5 | 5 (inline the logic) |
| Cloud/Azure steps | 4 | 0 |
| Topology routing | 4 | 3 (inline into pipeline) |
| Engine/CL2 steps | 9 | 0 |
| Shell scripts | 8 | 0 |
| Python modules | 6 | 0 |
| CL2 config templates | 11 | 0 |
| Datapath observer | 13 | 0 |
| **Other topologies/engines/clouds** | **0** | **~50+ directories/files** |

A standalone rewrite could reduce the **~68 files touched** down to **~45 files** by eliminating the routing indirection, and the overall repository could drop **50+ directories** of code for other test scenarios, other cloud providers, and Terraform modules.
