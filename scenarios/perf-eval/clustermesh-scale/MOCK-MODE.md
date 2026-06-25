# ClusterMesh Scale — MOCK mode (KWOK + mock-cilium-agent)

This scenario can run in **mock mode**, where each cluster's real workload nodes
are replaced by **KWOK virtual nodes + a forked mock-cilium-agent** (real Cilium
control plane, DryMode/fake datapath). This reduces the per-node cost from a whole
VM (~4 vCPU) to a free API object + a tiny Pod (~9m CPU / ~56Mi, measured), giving
roughly a **10× vCPU reduction** at the 10k-node target while keeping the entire
AKS + ACNS product surface (kube-apiserver, clustermesh-apiserver, kvstoremesh,
cilium-operator) **real** — those remain the System Under Test.

The mock framework itself (the agent fork, image build, and per-cluster deployer
`provision-kwok-layer.sh`) lives in the companion `mock-clustermesh/` tree. This
doc covers only the **telescope-side integration**.

## Architecture

```
Real (today)                          Mock mode
------------                          ---------
20 x D4s_v5 workload nodes/cluster    2 x D8s_v5 thin worker pool/cluster
  each = a real VM + kubelet            hosts ONLY the mock-cilium-agent Pods
  + real cilium-agent (DaemonSet)     100 KWOK virtual nodes/cluster (API objects)
  + real workload Pods                  each served by 1 mock-cilium-agent Pod
                                        (real watches/identities/policy/clustermesh
                                         consume; datapath faked)
```

The real AKS-managed cilium-agent still runs on the thin worker pool (it is the
harness agent); the **mock** agents are what represent the simulated nodes.

## What is integrated here (validated 2026-06-23)

| Piece | File | Notes |
|-------|------|-------|
| Thin-worker-pool tfvars | `terraform-inputs/azure-2-mock.tfvars` | `default_node_pool` = 2× D8s_v5 (hosts mock-agent Pods) instead of 20× D4s_v5. n=20 variant = same transform on `azure-20.tfvars`. |
| CL2 mock gating | `modules/.../config/config.yaml`, `modules/scale-test*.yaml`, `modules/clustermesh.yaml` | `CL2_MOCK_MODE=true` → workload Pods get `nodeSelector type=kwok` + the `kwok.x-k8s.io/node` toleration, and a PodMonitor for `app=mock-cilium-agent:9962` is added so Prometheus scrapes the mock agents. Default `false` → real runs unchanged. |
| Mock-agent PodMonitor | `modules/clustermesh/podmonitor-mock-agent.yaml` | Scrapes the mock agents on :9962 in the `mock-clustermesh` namespace. |
| AKS prometheus storage fix | `modules/python/clusterloader2/utils.py`, `clustermesh-scale/scale.py` | Passes `--prometheus-pvc-storage-class=managed-csi` for `provider=aks`. CL2's default `ssd`/`kubernetes.io/gce-pd` class does NOT provision on AKS → prometheus-k8s stays Pending → "no endpoints". |
| `CL2_MOCK_MODE` wiring | `clustermesh-scale/scale.py` (`--mock-mode`), engine `execute.yml` (re-export) | Matrix var `mock_mode` → `MOCK_MODE` → `CL2_MOCK_MODE` → overrides → templates. |
| Mock topology | `steps/topology/clustermesh-scale-mock/` | `validate-resources.yml` = base validate + `deploy-mock-layer.yml` (loops clusters, runs the vendored provision script). `execute`/`collect` delegate to base. |
| Vendored deploy scripts | `scenarios/perf-eval/clustermesh-scale/mock/` | `provision-kwok-layer.sh` + `attrition-check.sh`, vendored from `mock-clustermesh/deploy/`. |

## How the mock layer is deployed (the `clustermesh-scale-mock` topology)

After terraform provisions the clusters (Fleet + ACNS + thin worker pool) and
before the CL2 engine runs, a topology step must deploy the KWOK + mock-agent
layer on **each** cluster. This is exactly what `mock-clustermesh/deploy/provision-kwok-layer.sh`
does (validated standalone). Per cluster:

```bash
KUBECONFIG_FILE=<cluster-kubeconfig> \
  NODE_COUNT=100 \
  ACR_HOST=<registry>.azurecr.io \
  AGENT_TAG=<mock-agent-image-tag> \
  CONSUME_CLUSTERMESH=true \
  mock-clustermesh/deploy/provision-kwok-layer.sh
```

This is now wired as the **`clustermesh-scale-mock` topology** (see below).

The topology (`steps/topology/clustermesh-scale-mock/`) reuses the base
`clustermesh-scale` validation (Fleet/ACNS/clustermesh-apiserver readiness +
cross-cluster smoke on the real thin pool — mock-compatible because it only asserts
nodes Ready and runs before the mock layer is added), then runs `deploy-mock-layer.yml`
which loops every cluster and invokes the vendored `mock/provision-kwok-layer.sh`.
The CL2 execute/collect steps delegate to the base scenario unchanged.

The full `CL2_MOCK_MODE` flow: a matrix var `mock_mode: true` auto-exports as
`MOCK_MODE` → engine `execute.yml` re-exports `CL2_MOCK_MODE` → `scale.py configure
--mock-mode` writes `CL2_MOCK_MODE: true` into the overrides → the config templates
gate kwok-targeting + the mock PodMonitor.

## Running via the telescope pipeline

Add a stage to `pipelines/perf-eval/Network Benchmark/clustermesh-scale.yml` that
points at the mock topology + tfvars and sets the mock variables. The
`mock-cilium-agent` image must be pullable by the clusters (push to a
pipeline-accessible ACR; see `mock/README.md`).

```yaml
  - stage: azure_mock_n2
    dependsOn: []
    variables:
      MOCK_ACR_HOST: <registry>.azurecr.io   # hosts mock-cilium-agent:<tag>
      MOCK_AGENT_TAG: v26
      MOCK_NODE_COUNT: 100
      MOCK_CONSUME_CLUSTERMESH: true
    jobs:
      - template: /jobs/competitive-test.yml
        parameters:
          cloud: azure
          regions: [eastus2euap]
          engine: clusterloader2
          engine_input:
            image: "ghcr.io/azure/clusterloader2:v20250513"
            install: false
            operation_timeout: 15m
          topology: clustermesh-scale-mock
          terraform_input_file_mapping:
            - eastus2euap: "scenarios/perf-eval/clustermesh-scale/terraform-inputs/azure-2-mock.tfvars"
          matrix:
            n2_mock:
              cluster_count: 2
              mesh_size: 2
              cl2_config_file: config.yaml      # or pod-churn-combined.yaml for a real window
              test_type: mock-default
              namespaces: 1
              deployments_per_namespace: 2
              replicas_per_deployment: 5
              mock_mode: true                   # → CL2_MOCK_MODE
              hold_duration: 30s
              warmup_duration: 10s
              restart_count: 0
              api_server_calls_per_second: 5
              trigger_reason: ${{ variables['Build.Reason'] }}
```

For real measurements use a scenario with a steady-state window (e.g.
`pod-churn-combined.yaml`) — see the measurement-window note below. The n=20 tier
is the same stage with `azure-20-mock.tfvars` and `cluster_count: 20`.

## How to run CL2 in mock mode (validated recipe, local docker)

Set `CL2_MOCK_MODE: true` in the CL2 overrides (scale.py writes the overrides
file; add it there for the mock variant). The storage-class flags are applied
automatically for `provider=aks`. Locally-validated docker invocation:

```bash
docker run --rm --network host \
  -v <admin-kubeconfig>:/root/.kube/config \
  -v <config-dir>:/root/perf-tests/clusterloader2/config \
  -v <results-dir>:/root/perf-tests/clusterloader2/results \
  ghcr.io/azure/clusterloader2:v20250513 \
  --provider=aks --enable-prometheus-server=true \
  --prometheus-pvc-storage-class=managed-csi \
  --prometheus-storage-class-provisioner=disk.csi.azure.com \
  --kubeconfig /root/.kube/config \
  --testconfig /root/perf-tests/clusterloader2/config/config.yaml \
  --testoverrides=/root/perf-tests/clusterloader2/config/overrides.yaml \
  --report-dir /root/perf-tests/clusterloader2/results
```

(Use an **admin** (cert-based) kubeconfig so the CL2 container can auth without an
exec plugin.)

## Validation results (mockmesh3-1, 100 KWOK nodes + 100 mock agents)

- A full CL2 run (`config.yaml`, `CL2_MOCK_MODE=true`) returns **Status: Success**;
  the kwok-targeted workload deploys (KWOK acks Pods Running, `WaitForControlledPodsRunning`
  passes) and Prometheus scrapes all 100 mock-agent targets.
- With an adequate steady-state window, the `cilium.yaml` measurement reads the
  **mock** agents (Cilium Avg CPU Perc50 ≈ 0.008 cpu ≈ 8m, matching `kubectl top`),
  and `clustermesh-metrics.yaml` reads Identity Count / Remote Clusters Connected.

## Known consideration: measurement window

CL2's Prometheus measurements need the target scraped for **≥ ~2 scrape intervals
(≥30s)** during the start→gather window. The trivial **Phase-1** `config.yaml`
deploys a few Pods and gathers almost immediately (~7s window < the 15s scrape
interval), so *no* Prometheus metric — mock **or** apiserver — populates reliably.
Real scenarios (`pod-churn-combined`, `event-throughput`, soak) run for minutes and
do not have this issue. For short-window runs, apply the mock PodMonitor at
prometheus-init via `--prometheus-additional-monitors-path` so the mock agents are
scraped from the start (validated working).
