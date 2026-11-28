# CSI disk-boundary autoscale: 5,000 total nodes

## Overview

This scenario tests whether Azure Disk CSI attachment-slot exhaustion causes
AKS Cluster Autoscaler to add workload nodes. The runner increases StatefulSet
replicas; it does not manually scale node pools or set a 4,995-node minimum.
Each pod uses one unique PVC and dynamically provisioned Azure Disk and becomes
Ready only after reading back its own data from the mounted disk.

| Setting | Current value |
|---------|---------------|
| Region | `australiaeast` |
| Kubernetes version | `1.36` |
| AKS tier | `Standard` |
| Workload-node target | **4,995** |
| Fixed system nodes | **5**, excluded from the workload target |
| Total nodes at the target | **5,000** |
| Expected disk limit | **4 per workload node**, verified from live CSI data |
| Pods and distinct data disks at limit 4 | **19,980** |
| PVC request per pod | **4 GiB** |
| Random batch increment | **400-1,000 pods**; the final batch can be smaller |
| Configured batch interval | **20 minutes** |

The pod target is `4995 * live disk limit`, not a hard-coded 19,980.
Both the benchmark and manual qualification pipelines use this workload-node
target; smaller manual runs can request fewer nodes.

### Cluster-limit warning

AKS documents a [5,000-node maximum across all pools](https://learn.microsoft.com/en-us/azure/aks/quotas-skus-regions),
including system nodes. The target reaches that limit and leaves **no node-count
headroom for upgrade surge or temporary extra nodes**.

All five workload pools currently retain `max_count=1000`. Their combined
ceiling is **5,000 workload nodes**, or **5,005 including the system pool**,
which exceeds the documented cluster limit. These pool settings do not enforce
a safe cluster-wide maximum or guarantee that autoscaling stops at the target.
The runner fails if it observes more than 4,995 workload nodes.

To enforce a combined workload ceiling of 4,995, reduce the sum of the pool
maximums by five, for example by setting `csipool5.max_count=995`. That reduction
is **not applied in the current configuration**. Do not perform surge upgrades
at the full target; use a lower target and appropriate pool caps if headroom
is needed. Additional VM quota or IP addresses do not raise the AKS node limit.

## Infrastructure and workload

The [Terraform input](terraform-inputs/azure.tfvars) defines:

| Pool | SKU | Initial / minimum nodes | Maximum nodes | Autoscaling |
|------|-----|-------------------------|---------------|-------------|
| `system` | `Standard_D8ds_v5` | 5 / fixed | 5 / fixed | Disabled |
| `csipool1` | `Standard_D2ds_v5` | 0 / 0 | 1,000 | Enabled |
| `csipool2` | `Standard_D2ds_v5` | 0 / 0 | 1,000 | Enabled |
| `csipool3` | `Standard_D2ds_v5` | 0 / 0 | 1,000 | Enabled |
| `csipool4` | `Standard_D2_v5` | 0 / 0 | 1,000 | Enabled |
| `csipool5` | `Standard_D2_v5` | 0 / 0 | 1,000 | Enabled |

Workload VMs have 2 vCPUs and 8 GiB of memory. All workload pools use
`cas=dedicated`, `max_pods=30`, and no pinned availability zones. The pod-count
limit is **not** a four-disk scheduling cap. Node OS disk capacity is not
explicitly set by this scenario.

The [disk workload](../../../modules/python/clusterloader2/autoscale/config/disk_statefulset.yaml)
uses a parallel StatefulSet with one `ReadWriteOnce` PVC per pod and requests
only 10m CPU and 32 MiB memory, so CPU/memory packing is not the intended scaling
constraint. It explicitly retains PVCs when pods are recreated or the
StatefulSet is scaled down or deleted. Final namespace cleanup removes storage.

The `managed-csi` StorageClass must use `disk.csi.azure.com`,
`WaitForFirstConsumer`, and reclaim policy `Delete`. Use a non-premium disk SKU
such as `StandardSSD_LRS`: `Standard_D2_v5` does not support Premium SSD disks.
Before the first pod, validation requires zero selected workload nodes.

## Execution flow

The [runner](../../../modules/python/clusterloader2/autoscale/disk_autoscale.py)
uses the following flow:

1. **Bootstrap from zero.** Request one pod and require its `FailedScheduling`
   and `TriggeredScaleUp` events. Verify that the first workload node becomes
   Ready and the pod has a mounted, working disk. Bootstrap demonstrates
   scale-from-zero, not disk exhaustion on an existing node.
2. **Discover capacity.** Read the first node's positive Azure Disk allocatable
   count from `CSINode`. Subsequent nodes must advertise the same limit.
3. **Submit overlapping batches.** Submit the first batch immediately after
   bootstrap. Draw a new random increment of 400-1,000 pods for every batch and
   cap total replicas at `4995 * live disk limit`.
4. **Maintain the configured cadence.** Request the next batch 20 minutes after
   the preceding request, regardless of earlier pod readiness. Early readiness
   does not shorten the interval. API work can delay the actual next request.
5. **Require disk-driven scale-out evidence.** For at least one newly requested
   ramp pod, require both a `FailedScheduling` event identifying a positive
   volume-count limit and a `TriggeredScaleUp` event. Evidence is required once
   for the ramp, not separately for each batch.
6. **Validate the final state.** Require exactly 4,995 Ready, uncordoned workload
   nodes and `4995 * live disk limit` Running, Ready pods. Verify full per-node
   disk density, unique bound Azure Disk PVs, and successful VolumeAttachments
   to the pods' actual nodes. At limit four, this means 19,980 distinct disks.

For example, random increments 400, 800, 1,000 produce pod totals
`1 -> 401 -> 1201 -> 2201` and workload node targets `1 -> 101 -> 301 -> 551`.
Intermediate node targets are `ceil(requested pods / live disk limit)`, not
isolated topology checks: batches overlap. The number of stages varies per run.
No HPA is needed. Autoscaler maximums are ceilings, not desired node counts,
and assigned pods blocked on disk attachment generally do not trigger scale-out.

Progress logs show the current Ready/observed workload nodes and Running,
Ready/observed pods alongside their targets. Counts reflect readiness decreases,
not just cumulative first-observed readiness samples. Logs update when counts
change and at least once per minute while polling proceeds. System nodes are
excluded; elapsed time starts at the stage request or first ramp request.
Extra workload nodes, invalid disk placement, missing disk-limit/autoscaler
evidence, and timeouts fail the test.

## Bounded overpacking recovery

Recovery is active throughout the timed ramp and final readiness wait. It
recreates excess blocked pod instances so they return to scheduling without
increasing replicas, deleting their disks, or manually scaling pools.

| Recovery setting | Value |
|------------------|-------|
| Check interval | 60 seconds |
| Grace after detection | 120 seconds |
| Maximum accepted deletions | 3 per StatefulSet pod name, across replacement UIDs |

A candidate must be assigned, Pending, and not terminating. Its node must be
Ready, uncordoned, and advertise the expected live CSI limit. Assigned benchmark
pods must exceed that limit, while exactly that many non-terminating benchmark
pods are already Running. Pending alone is not sufficient.

At limit four, a node with four Running pods and six excess Pending pods
qualifies; a node still bringing its first four pods into Running does not.
The same candidate must survive the grace period. Regular monitoring resets
tracking when identity, assignment, or qualifying state changes.

Before deletion, the runner refreshes node/pod placement and CSI limits, then
reads each candidate again. Normal pod deletion includes UID and resourceVersion
preconditions. Pod read/delete HTTP 404/409 races are logged and skipped without
consuming an attempt; other API errors fail the run. Running and terminating
pods are not selected, and there is no force deletion.

The StatefulSet recreates deleted pods with the same names and existing PVCs,
but new UIDs and initially no node assignments. They can use existing compatible
capacity or become unschedulable and trigger further scale-out. Persistent
overpacking on replacements starts a new grace period. A fourth required
recovery fails explicitly; recovery does not reset the final-wait deadline.

The report's `overpacking_recovery` records the interval, grace period, retry
limit, accepted-deletion counts by pod name, and deletion records containing
pod name/UID, node, disk limit, attempt, UTC request timestamp, and outcome.
Recovery delays remain included in the original batch's readiness latency;
replacement UIDs reset readiness samples without restarting the batch timer.

### Latency and limitations

Under responsive API conditions, deletion starts approximately **2-3 minutes**
after overpacking begins: up to one minute for detection, then two minutes of
grace, plus polling/API overhead. This grace period does not pause the ramp.

Recovery API calls execute sequentially inside the monitoring loop. For a pass
recovering all candidates across `N` affected nodes and `P` excess pods, the
additional requests are approximately `2*N + 2*P + 2`: CSI checks, fresh node/pod
lists, and one pod read and deletion per candidate. Large passes can delay
readiness observations and actual batch submission. Kubernetes scheduling and
autoscaling continue independently, although the requests add API load.

There are **no explicit recovery request timeouts or per-iteration work budgets**.
The retry limit bounds accepted deletions, not wall-clock latency; a stalled
request can prevent the monitor from reaching its deadline check.

This mitigates persistent overpacking, not the underlying scheduling race.
It does not guarantee the node target, diagnose every Pending cause, or recover
nodes whose Running pods do not fill their disk slots. Volume topology and
detach delays can still block placement. There is no CSI startup taint or hard
four-pod scheduler cap in the current scenario. Qualify recovery at a smaller
scale before relying on a full-size run. Sequential execution has no recovery.

## Schedule and execution budgets

The benchmark is scheduled on `main` every Friday at **18:00 IST / 12:30 UTC**,
even without code changes. Manual runs are also supported.

| Budget | Current setting |
|--------|-----------------|
| Bootstrap scale-up | 5 hours |
| Final readiness wait, starting at the last replica request | 5 hours |
| Storage cleanup | 6 hours |
| Workload-node scale-down after storage cleanup | 6 hours |
| Pipeline job | 48 hours |
| Resource deletion lifetime | 60 hours |

At a disk limit of four, the 19,980-pod target takes 20-50 random ramp batches.
The configured intervals alone span approximately **6 hours 20 minutes to
16 hours 20 minutes**, from the first ramp request to the last, before API
delays. Earlier Pending batches do not stop later submissions. These settings
are execution budgets, not guarantees of completion or strict request timeouts.
Provisioning, recovery, validation, and cleanup all consume time.

## Capacity and access prerequisites

- **Compute:** 4,995 two-vCPU workload nodes require 9,990 vCPUs; the five
  eight-vCPU system nodes add 40, for **10,030 regional vCPUs** at the target.
  The DDSv5/Dv5 split depends on final pool sizes. Family ceilings are
  **6,040 DDSv5 vCPUs** including the system pool, and **4,000 Dv5 vCPUs**.
  Those simultaneous ceilings correspond to the unsupported 5,005-node pool
  maximum, not the benchmark target. Check current regional/family quotas,
  SKU restrictions, physical capacity, and cost approval before each run.
  Quota is not a capacity reservation.
- **Networking:** `10.128.0.0/11` provides 8,192 overlay `/24` pod blocks.
  Separately verify at least 5,000 usable node-subnet addresses and operational
  IP headroom. Extra addresses do not provide node-count headroom.
- **Storage:** at limit four, plan for 19,980 distinct workload data disks and
  5,000 managed OS disks. Check storage SKU compatibility, quotas, provisioning
  throughput, and cleanup time.
- **Access:** both pipelines set `AAD_ENABLED: 'true'`. The Terraform identity
  receives a cluster-scoped AKS RBAC Cluster Admin assignment and must be allowed
  to create/delete role assignments. Validation configures kubelogin for Azure
  CLI authentication and waits up to five minutes for authorization to propagate.
- **Qualification:** confirm regional Kubernetes-version availability and
  validate the scenario at a smaller scale before launching the full target.

## Results and cleanup

`disk-autoscale.json` records the live disk limit and each bootstrap/ramp batch:
requested replicas, workload node target, request timestamp, pod readiness
samples, and result. Bootstrap retains its isolated node/storage timings and
event messages. Overlapping batches do not report isolated topology timings.
The report records `batch_interval_seconds`, `ramp_scale_up_evidence`,
`final_pods_per_node`, and `ramp_all_pods_storage_ready_seconds` (elapsed from
the first ramp request until final readiness). Ramp batches are marked successful
only after final validation passes. `new_pod_count` records the actual
increment, including the bootstrap and capped final batch. Timings use polling
and have roughly five-second resolution. These are random-batch timings, **not** bulk
scale-up P50/P70/P90/P99/P100; a separate common-start bulk phase is needed
before reporting those metrics.

### End-to-end pod readiness latency

Each stage includes `pod_readiness_samples`, keyed by the newly requested
pod's name, with its UID and `e2e_ready_seconds`. Latency starts immediately
before the StatefulSet replica-change API call and ends when the runner first
observes that pod Running with `Ready=True`. It includes API processing,
controller/pod creation, scheduling, node autoscaling when needed, disk setup,
container startup, and the storage readiness probe. Previously existing pods
are excluded from the new stage's samples.

`pod_readiness_e2e_seconds` appears both in each stage and at the report's top
level, with `sample_count`, `expected_pod_count`, `complete`, `p50`, `p90`, and
`p99`. Percentiles use NumPy's linear interpolation. The run-level distribution
combines every individual pod's latency relative to its own batch request,
including bootstrap, rather than averaging stage percentiles or measuring from
the beginning of the entire multi-stage run.

These are first-observed readiness latencies, with approximately five-second
polling resolution plus API overhead, not exact Kubernetes transition times.
Readiness changes between polls can be missed. A replacement pod's UID resets
that ordinal's sample if detected while observing its batch, including after
later batches have been submitted.

If a stage fails or times out, its observed samples are still saved. Incomplete
batch/run summaries have `complete: false` and null percentiles, avoiding a
misleading distribution that silently excludes unfinished pods. Check the
stage/run `result` as well: complete readiness samples do not imply the
autoscaling evidence, disk validation, or cleanup succeeded. These latency
percentiles are distinct from time-to-X%-Ready thresholds measured from one
common workload scale-up request.

### Per-pod and per-node timing tables

The runner writes `pod-readiness.csv` and `node-readiness.csv` alongside the
JSON report. The existing pipeline artifact publication includes both files.
The same rows appear in the JSON as `pod_timings` and `node_timings` and remain
available under `data` in collected Telescope results.

| Pod column | Meaning |
|------------|---------|
| `pod_name`, `pod_uid`, `node_name` | Pod identity and assigned workload node |
| `requested_at` | UTC start of this pod's batch request; the E2E start |
| `pod_created_at` | Kubernetes pod creation timestamp |
| `pod_started_at` | Kubernetes `status.startTime`: when the kubelet acknowledged the pod, not necessarily container process start |
| `ready_transition_at` | Kubernetes Ready condition's transition timestamp when readiness was first observed |
| `ready_observed_at` | UTC time the runner first observed the pod Running and Ready |
| `e2e_ready_seconds` | Monotonic elapsed seconds from batch request to first-observed readiness |
| `phase` | Last observed pod phase, or `NotObserved` if it never appeared |

The node table lists every new workload node observed during the test, once,
excluding the fixed system nodes and previously measured nodes in later fill
stages. It includes `node_name`, `node_uid`, `requested_at`,
`node_registered_at`, `ready_transition_at`, `ready_observed_at`, and
`e2e_ready_seconds`. Bootstrap node E2E starts at the bootstrap request.
All ramp nodes use the **first ramp request** as their common origin and are
stored once under that batch's timing table: overlapping requests cannot
reliably be attributed to individual nodes. Node E2E ends when first observed
Ready and not cordoned. `node_registered_at` is
the Kubernetes Node object's creation time, **not** Azure VM creation time.
Nodes that never registered cannot be named in the table.

Pod E2E includes node creation and node readiness waiting when that pod requires
new capacity: its timer starts before requesting replicas, not after the node
or pod is created. Pods placed on existing nodes naturally do not incur that
scale-up wait. Pod/node durations overlap and must not be added together.
The pod's `node_name` joins the two tables.

Requested pods and observed nodes that never became Ready retain null readiness
timestamps/durations (blank CSV cells), not zero-duration successes. Missing
Kubernetes timestamps also remain null. CSVs are exported on failure as well;
an export error fails the run but the JSON report is still written. Timestamp
columns use UTC wall time; E2E durations use a monotonic clock, so small timestamp
differences or wall-clock corrections need not exactly match elapsed durations.
Historical reports without these fields cannot recover exact per-pod timestamps
from their all-pods-ready stage totals.

The runner owns a unique namespace and deletes it even after a failed stage.
Cleanup verifies removal of its PVCs, PVs, and VolumeAttachments and waits for
the workload pool to return to zero nodes. The five system nodes remain during
this check. Failed stages and cleanup errors
are written to the report and fail the pipeline. Warning events and CSI logs
are also collected. Structured results use the `disk_boundary` autoscale type.

## Pipeline

Manually queue [the validation pipeline](../../../pipelines/system/new-pipeline-test.yml)
or [the CSI pipeline](../../../pipelines/perf-eval/CSI%20Benchmark/csi-autoscale-5k.yml).
Both request `node_count: 4995`, passed to the runner as `--node-count 4995`.
The runner accepts only node-based targets; omitting `--node-count` retains
the default ten-node test. The final pod count is the node target multiplied
by the live CSI disk limit.
Both pipelines pass `--batch-interval-seconds 1200`. Direct CLI callers default
to sequential execution (`--batch-interval-seconds 0`), which retains per-stage
validation and timeouts. In timed mode, the scale-up timeout applies to bootstrap
and then to the final wait starting at the last replica request; storage cleanup
and node scale-down have separate timeouts.

The generic runner accepts 2-5,000 workload nodes, but this scenario must account
for its five fixed system nodes: 5,000 workload nodes would exceed the AKS total
limit. System nodes are never included in workload-node counts or workload-pod
readiness samples. The scenario target is 4,995; see the cluster-limit warning
above before changing either the target or pool caps.
