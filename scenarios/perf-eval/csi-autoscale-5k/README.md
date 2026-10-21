# CSI disk-boundary autoscale

## Overview

Verifies that exhausting Azure Disk CSI attachment slots causes AKS Cluster
Autoscaler to add workload nodes. Each StatefulSet pod uses one PVC and one
distinct dynamically provisioned Azure Disk, requests 4 GiB, and becomes Ready
only after reading back its own data from the mounted disk. Small CPU/memory
requests keep the intended constraint on disk attachments, not CPU packing.

The benchmark and manual qualification pipeline target **exactly 5,000 workload
nodes**, excluding the five fixed system nodes. At four disks per node this
requires **20,000 workload pods and disks**. Smaller manual tests can specify
a lower node-count target.

This configuration requires an approved AKS cluster-size limit exception:
5,000 workload nodes plus five system nodes total **5,005 nodes**, above the
documented 5,000-node cluster limit. Confirm that the exception applies to the
subscription, region, and cluster before running either pipeline.

## Infrastructure and workload

- Five `Standard_D2ds_v4` workload pools, initially zero nodes, autoscaling min=0,
  each with a maximum of 1,000. All share `cas=dedicated`.
  This matches the workload SKU in upstream main's 500/1,000-node autoscaler
  scenarios; eligibility still depends on the subscription and region.
- Five separate fixed system nodes are excluded from test node counts.
- `max_pods=30` is a pod limit, not a disk attachment limit.
- The node OS disk capacity is not explicitly set by this scenario.
- `managed-csi` must use `disk.csi.azure.com`, `WaitForFirstConsumer`, and `Delete`.
- The runner requires zero workload nodes before creating the first pod. It
  reads the actual attachment limit from the first autoscaled node's `CSINode`;
  all subsequent nodes must advertise the same positive limit.

For the expected limit of four disks per workload node:

1. Request one pod while no workload nodes exist. Require `FailedScheduling`
   and `TriggeredScaleUp` events for that pod, then verify the first workload
   node becomes Ready and hosts the pod with a mounted, working disk. Unlike
   later overflows, this bootstrap cannot be caused by disk-slot exhaustion:
   there is no eligible workload node yet.
2. Read the live CSI disk limit. For each subsequent batch, draw a fresh random
   integer from 60 through 100 (inclusive) and add that many pods to the current
   replica count. Cap the final batch at `5000 * live disk limit` total pods
   (20,000 for a limit of four); it may add fewer than 60.
3. Compute expected workload nodes as `ceil(total pods / live disk limit)`.
   A batch may fit existing nodes or require several new nodes.
4. For a growing batch, require a newly requested pod's `FailedScheduling` event
   to identify a positive volume-count limit and its `TriggeredScaleUp` event.
   The count in the scheduling message can change as nodes join during a batch.
5. Verify all expected nodes become Ready and every new node hosts a new batch
   pod with its disk. Wait for the batch to complete before requesting the next.
6. Repeat until 5,000 workload nodes host the final 20,000 pods/disks.

For example, random increments 60, 80, 100 produce pod totals
`1 -> 61 -> 141 -> 241` and workload node totals `1 -> 16 -> 36 -> 61`.
The number of stages varies per run, averaging about 250 batches after bootstrap.
The final cluster has 5,005 nodes including the five
system nodes. No HPA is needed: the runner changes workload replicas, while
the real AKS Cluster Autoscaler changes node counts.

The test changes only StatefulSet replicas, never node-pool node counts. It
checks exact node and pod counts, pod readiness, per-node density, distinct
Azure Disk PV handles, and successful VolumeAttachments to the correct nodes.
Extra nodes, unrelated scheduling constraints preventing disk-limit evidence,
missing autoscaler evidence, and timeouts fail the test.

## Schedule and execution budgets

The benchmark runs on `main` every Friday at 18:00 IST (12:30 UTC), even without
code changes. Each scale-up stage allows three hours. Storage cleanup and subsequent
scale-down each allow six hours, within a 48-hour job budget. Resources have a
60-hour deletion lifetime. These budgets do not guarantee that the run will
finish: provisioning, serial batches, validation, and cleanup all consume time.

Before enabling the schedule, verify regional VM/vCPU and disk quotas, capacity,
networking, agent job-duration limits, the cluster-size limit exception, and cost
approval for 20,000 workload disks and 5,005 cluster nodes. The disk limit is
discovered at runtime; the workload-node target stays at 5,000, while the final
pod/disk target is `5000 * live disk limit`. The configured workload pools
support at most 5,000 nodes in total.
Storage verification lists PVs
once per completed stage rather than issuing one read request per pod.

## Results and cleanup

`disk-autoscale.json` records the live disk limit and each bootstrap/fill/overflow stage:
requested replicas, workload node count, request timestamp, elapsed time to
node readiness, all pods Running, all pods storage-ready, per-node pod counts,
and scheduler/autoscaler event messages. `new_pod_count` records the actual
increment, including the bootstrap and capped final batch. Timings use polling
and have roughly five-second resolution. These are random-batch timings, **not** bulk
scale-up P50/P70/P90/P99/P100; a separate common-start bulk phase is needed
before reporting those metrics.

### End-to-end pod readiness latency

Each stage now includes `pod_readiness_samples`, keyed by the newly requested
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
that ordinal's sample if detected during the same stage.

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
`e2e_ready_seconds`. Node E2E starts at the workload request that triggered it
and ends when first observed Ready and not cordoned. `node_registered_at` is
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
Both request `node_count: 5000`, passed to the runner as `--node-count 5000`.
The runner accepts only node-based targets; omitting `--node-count` retains
the default ten-node test. The final pod count is the node target multiplied
by the live CSI disk limit.
The scale-up timeout is per
stage; storage cleanup and node scale-down have separate timeouts.

Qualify changes at smaller scales before launching the full workload. The runner
rejects targets requiring more than 5,000 workload nodes; system nodes are never
included in workload-node counts or workload-pod readiness samples.
