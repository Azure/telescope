---
name: create-pipeline-benchmark
description: >
  Scaffold a new Telescope KCL pipeline benchmark (a `pipeline.k` file plus its
  companion manifests) modeled on existing benchmarks such as
  `kcl/ccp_team/hyperscale_pod_scheduling/pipeline.k`. Use this skill whenever
  the user asks to "create a pipeline benchmark", "add a new benchmark",
  "scaffold a benchmark pipeline", "make a new KCL pipeline", or otherwise wants
  to author a new benchmark that provisions an AKS cluster, runs a workload
  (e.g. ClusterLoader2 / KWOK), and tears it down. The skill interviews the user
  for the required parameters, writes the KCL source, and generates the YAML.
---

# Create Pipeline Benchmark

## Overview

A Telescope benchmark lives in a folder under `kcl/<team_or_group>/<benchmark_name>/`
and contains:

| File | Purpose |
|------|---------|
| `pipeline.k` | KCL source defining the pipeline (stages, jobs, steps) |
| `pipeline.yaml` | Generated Azure DevOps YAML (do **not** hand-edit) |
| `cl2*.yaml` | ClusterLoader2 manifest(s) for the workload (optional) |
| `kwok-node.yaml` | KWOK fake-node template (optional, for scale tests) |

The typical job flow:

```
SetRunId → InstallPythonDependencies → Login → CreateResourceGroup
  → Create cluster (az aks create / az rest) → WaitForClusterSucceeded
  → CreateNodePool(s) → GetCredentials → [CreateKwokNodes]
  → RunClusterLoader2 → PrintCl2PodLogs → DeleteResourceGroup
```

---

## Prerequisites

- `kcl` CLI installed (see the **kcl** skill if missing)
- Working from the repo root (`/home/vsalim/telescope`)
- Reusable building blocks live in `kcl/lib/steps/` (`azure`, `common`, `k8s`)
  and defaults in [kcl/lib/const.k](kcl/lib/const.k)

---

## Step 1: Interview the User for Parameters

Ask for the following. Suggest the listed defaults; only **benchmark name** and
**workload sizing** are strictly required.

**Identity & placement**
- **Benchmark name** (`<NAME>`) — folder name, e.g. `hyperscale_pod_scheduling`
- **Team / group folder** (`<GROUP>`) — e.g. `ccp_team`, `apiserver_benchmark`
- **Pipeline display name** — e.g. `"Hyperscale Pod Scheduling Rate"`
- **Location** (default `westus2`)
- **Subscription ID** (default `const.DEFAULT_SUBSCRIPTION_ID`)

**Cluster sizing**
- **System node count** (default `3`) and **VM size** (default `Standard_D8S_v4`)
- **Max pods per node** (default `250`)
- **Kubernetes version** (default `1.35.0`)

**Workload**
- **Workload type**: `clusterloader2`, `kwok` scale test, or `custom script`
- **Node count(s)** to scale to — a single value or a map of sizes
  (e.g. `{"H2": 2000, "H4": 4000, "H8": 8000}` produces one stage per size)
- **CL2 image** (default `ghcr.io/azure/clusterloader2:<tag>`) and **namespace**
  (default `clusterloader2`), if using ClusterLoader2
- Whether KWOK fake nodes are needed, and **nodes-per-controller** (default `100`)

> If the user gives a single node count, generate a single-job pipeline (like
> [kcl/example_pipeline/pipeline.k](kcl/example_pipeline/pipeline.k)). If they
> give a size→count map, generate one stage per size (like
> [kcl/ccp_team/hyperscale_pod_scheduling/pipeline.k](kcl/ccp_team/hyperscale_pod_scheduling/pipeline.k)).

---

## Step 2: Create the Benchmark Folder and `pipeline.k`

Write `kcl/<GROUP>/<NAME>/pipeline.k`. Use this template as a starting point —
fill placeholders from the interview and drop steps that aren't needed.

```python
import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure
import lib.steps.common
import lib.steps.k8s
import lib.util

SUBSCRIPTION_ID = const.DEFAULT_SUBSCRIPTION_ID
RESOURCE_GROUP = "$(RUN_ID)"
LOCATION = "<LOCATION>"
CLUSTER = "<NAME>"
CL2_NAMESPACE = "clusterloader2"
CL2_POOL = azure.NodePool {
    name = "cl2pool"
    sku = "Standard_D8S_v4"
    count = 1
    taintPrefix = "cl2pool"
}

createClusterScript = """
az aks create \\
  --name "${CLUSTER}" \\
  --resource-group "${RESOURCE_GROUP}" \\
  --subscription "${SUBSCRIPTION_ID}" \\
  --location "${LOCATION}" \\
  --kubernetes-version "1.35.0" \\
  --dns-name-prefix "${CLUSTER}-dns" \\
  --tier standard \\
  --nodepool-name systempool \\
  --node-count 3 \\
  --node-vm-size "Standard_D8S_v4" \\
  --max-pods 250 \\
  --network-plugin azure \\
  --network-plugin-mode overlay \\
  --pod-cidr 10.64.0.0/10 \\
  --service-cidr 10.0.0.0/16 \\
  --dns-service-ip 10.0.0.10 \\
  --outbound-type managedNATGateway \\
  --nat-gateway-managed-outbound-ip-count 10 \\
  --enable-managed-identity \\
  --generate-ssh-keys
"""

output = ap.Pipeline {
    name = "<DISPLAY_NAME>"
    pool = const.DEFAULT_POOL

    parameters = [
        ap.Parameter {
            name = "run_id"
            displayName = "Run ID (leave empty to auto-generate)"
            type = "string"
            default = "default"
        }
    ]

    jobs = [
        job.Job {
            job = "benchmarking"
            displayName = "Benchmarking"
            timeoutInMinutes = 1440
            steps = [
                common.SetRunId(),
                common.InstallPythonDependencies(),
                azure.Login(const.DEFAULT_SERVICE_CONNECTION, SUBSCRIPTION_ID, LOCATION),
                azure.CreateResourceGroup(const.DEFAULT_SERVICE_CONNECTION, RESOURCE_GROUP, LOCATION, SUBSCRIPTION_ID),
                azure.AzCli(const.DEFAULT_SERVICE_CONNECTION, "Create cluster", createClusterScript),
                azure.WaitForClusterSucceeded(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, RESOURCE_GROUP, SUBSCRIPTION_ID),
                azure.CreateNodePool(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, RESOURCE_GROUP, SUBSCRIPTION_ID, CL2_POOL),
                azure.GetCredentials(const.DEFAULT_SERVICE_CONNECTION, CLUSTER, RESOURCE_GROUP, SUBSCRIPTION_ID),
                k8s.RunClusterLoader2(const.DEFAULT_SERVICE_CONNECTION, CL2_NAMESPACE, manifest = "kcl/<GROUP>/<NAME>/cl2.yaml"),
                k8s.PrintCl2PodLogs(const.DEFAULT_SERVICE_CONNECTION, CL2_NAMESPACE),
                azure.DeleteResourceGroup(const.DEFAULT_SERVICE_CONNECTION, RESOURCE_GROUP, SUBSCRIPTION_ID)
            ]
        }
    ]
}
```

**Multi-size variant:** when the user provides a size→count map, follow the
pattern in [kcl/ccp_team/hyperscale_pod_scheduling/pipeline.k](kcl/ccp_team/hyperscale_pod_scheduling/pipeline.k):
define `NODE_COUNTS`, a `makeBenchmarkingJob(size, ...)` lambda, a
`makeStage(size)` lambda, and `stages = [makeStage(s) for s in sizes]`.

**KWOK scale tests:** add a KWOK node pool and expand
`*k8s.CreateKwokNodes(<NODE_COUNT>, params = {...})` before `RunClusterLoader2`,
and create a `kwok-node.yaml` template (copy and adapt an existing one).

---

## Step 3: Add Workload Manifests

If using ClusterLoader2, create the `cl2*.yaml` manifest(s) referenced by the
`manifest =` argument. Copy and adapt an existing one (e.g.
[kcl/example_pipeline/cl2.yaml](kcl/example_pipeline/cl2.yaml)) to match the
target object counts / QPS for this benchmark.

---

## Step 4: Generate the YAML

Use the **generate-yaml** skill, or run directly:

```bash
kcl run kcl/<GROUP>/<NAME>/pipeline.k -S output -o kcl/<GROUP>/<NAME>/pipeline.yaml
```

If `pipeline.yaml` exceeds 2 MB (Azure DevOps limit), split it:

```bash
python3 scripts/split_pipeline.py kcl/<GROUP>/<NAME>/pipeline.yaml --repo-root .
```

---

## Step 5: Verify

- Confirm the KCL compiles without errors (the `kcl run` above succeeds).
- Sanity-check the generated `pipeline.yaml` steps match the intended flow.
- Reference the available building blocks if a step is missing:
  - `lib.steps.azure` — `Login`, `CreateResourceGroup`, `AzCli`,
    `CreateNodePool`, `WaitForClusterSucceeded`, `GetCredentials`,
    `DeleteResourceGroup`
  - `lib.steps.common` — `SetRunId`, `InstallPythonDependencies`,
    `RecordCurrentTime`, `UploadResult`
  - `lib.steps.k8s` — `CreateKwokNodes`, `RunClusterLoader2`, `PrintCl2PodLogs`
