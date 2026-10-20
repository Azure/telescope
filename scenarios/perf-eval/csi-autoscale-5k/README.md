# CSI disk-boundary autoscale

## Overview

Verifies that exhausting Azure Disk CSI attachment slots causes AKS Cluster
Autoscaler to add workload nodes. Each StatefulSet pod uses one PVC and one
distinct dynamically provisioned Azure Disk, requests 4 GiB, and becomes Ready
only after reading back its own data from the mounted disk. Small CPU/memory
requests keep the intended constraint on disk attachments, not CPU packing.

The first qualification is limited to **10 workload nodes**. The existing
scenario/pipeline names retain `5k`, but the 5,000-node profile is intentionally
disabled until the small test passes.

## Infrastructure and workload

- One `Standard_D2ds_v4` workload pool, initially zero nodes, autoscaling min=0/max=10.
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
2. Read the live CSI disk limit, then request four pods and verify one fully
   occupied workload node.
3. Request a fifth pod. Require its `FailedScheduling` event to identify the
   volume-count limit on the existing node and its `TriggeredScaleUp` event.
4. Verify a second node becomes Ready and hosts the overflow pod.
5. Fill both nodes with eight pods, then request pod nine.
6. Repeat through ten workload nodes, finally filling them with 40 pods/disks.

There are 20 measured stages: one scale-from-zero bootstrap, ten fills, and
nine disk-capacity overflows. The final cluster has 15 nodes including the five
system nodes. No HPA is needed: the runner changes workload replicas, while
the real AKS Cluster Autoscaler changes node counts.

The test changes only StatefulSet replicas, never node-pool node counts. It
checks exact node and pod counts, pod readiness, per-node density, distinct
Azure Disk PV handles, and successful VolumeAttachments to the correct nodes.
Extra nodes, unrelated scheduling constraints preventing disk-limit evidence,
missing autoscaler evidence, and timeouts fail the test.

## Results and cleanup

`disk-autoscale.json` records the live disk limit and each bootstrap/fill/overflow stage:
requested replicas, workload node count, request timestamp, elapsed time to
node readiness, all pods Running, all pods storage-ready, per-node pod counts,
and scheduler/autoscaler event messages. Timings use polling and have roughly
five-second resolution. These are staged boundary timings, **not** bulk
scale-up P50/P70/P90/P99/P100; a separate common-start bulk phase is needed
before reporting those metrics.

The runner owns a unique namespace and deletes it even after a failed stage.
Cleanup verifies removal of its PVCs, PVs, and VolumeAttachments and waits for
the workload pool to return to zero nodes. The five system nodes remain during
this check. Failed stages and cleanup errors
are written to the report and fail the pipeline. Warning events and CSI logs
are also collected. Structured results use the `disk_boundary` autoscale type.

## Pipeline

Manually queue [the validation pipeline](../../../pipelines/system/new-pipeline-test.yml)
or [the CSI pipeline](../../../pipelines/perf-eval/CSI%20Benchmark/csi-autoscale-5k.yml).
Both currently run the same 10-node boundary test. The scale-up timeout is per
stage; storage cleanup and node scale-down have separate timeouts.

Only after this run passes should qualification expand to 100, 500, 1,000,
and 5,000 workload nodes, with appropriately sized node pools, quotas, and
batch-based measurements. The current runner rejects targets above ten.
