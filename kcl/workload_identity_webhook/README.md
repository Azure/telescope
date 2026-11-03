# Workload Identity webhook benchmark

One manual ADO job provisions a dedicated AKS Standard H2 cluster or reuses an
existing cluster, and runs kperf **three times sequentially on the ADO agent**:
50, 100, then 150 Pod CREATEs/sec, each for 10 minutes. After each run, request
deletion of its namespace without waiting, then pause for five minutes,
including after the final run.

## Cluster selection

| Parameter | Default | Behavior |
|---|---|---|
| `existing_resource_group` | `none` | Existing Azure resource group containing the cluster |
| `existing_cluster` | `none` | Existing AKS cluster name; must be supplied with the resource group |
| `keep_cluster` | `false` | Retain a newly created cluster and its Prometheus workspace; existing resource groups are always retained |

Leave both existing-cluster parameters as `none` (or empty) to create a new cluster.
Supplying only one fails before provisioning or traffic.

For example, reuse the retained benchmark cluster with
`existing_resource_group=wi-84842-1` and `existing_cluster=wi-webhook`.
The cluster must be in subscription `b8ceb4e5-f05b-4562-a9f5-14acb1f24219`.
Azure resource-group names are independent of the benchmark namespaces.

Reuse skips resource-group/cluster/node-pool and Prometheus workspace creation,
aks-preview installation, and monitoring enablement. Operators must provide an existing WI-enabled cluster.
In both modes, each rate's WI preparation idempotently applies its namespace and
ServiceAccount `pod-benchmark`, then sets `azure.workload.identity/client-id` to
the dummy UUID with `--overwrite`. Any previous client-ID annotation on this
benchmark ServiceAccount is replaced. Each namespace is dedicated to that phase.
Other reused cluster settings, including monitoring, remain unchanged.

Both modes fetch credentials and install kperf once. The per-rate steps prepare
WI resources and render a profile using `$(RUN_ID)-r<rate>` as both the namespace
and the phase identifier, for example `wi-85212-1-r50`. New builds and job attempts
get distinct names. Repeated preparation works for an existing Active phase
namespace; a Terminating namespace fails explicitly without waiting or removing
finalizers. Namespace cleanup leaves namespaces from previous runs untouched.

## New-cluster configuration

- Subscription: `b8ceb4e5-f05b-4562-a9f5-14acb1f24219`; region: `westus2`.
- System pool: three `Standard_D4_v4` nodes.
- Worker pool: three `Standard_D2s_v5` nodes, retained as requested but not used
  to host the traffic driver.
- OIDC and workload identity enabled; webhook resources/replicas are not tuned.
- The pipeline creates `wi-benchmark-prometheus`, an Azure Monitor workspace,
  in the cluster's resource group before enabling managed Prometheus during
  cluster creation. No separate `wi-benchmark-monitoring` group is required.
  The pipeline identity needs permission to create the workspace and onboard
  the cluster. This enables metrics, not container stdout/stderr logging;
  no Log Analytics workspace is provisioned.
- A benchmark ServiceAccount annotated with dummy client ID
  `00000000-0000-4000-8000-000000000001`. This preserves `AZURE_CLIENT_ID`
  injection without provisioning a workload managed identity. No federated
  credential or Azure role assignment is needed: this admission-only workload
  does not perform token exchange. Use a real identity for token-exchange tests.

[load-profile.yaml](./load-profile.yaml) is a template rendered before each phase:

- `__RATE__` becomes 50, 100, or 150 Pod CREATEs/sec; 600-second generation window each.
- `total: 0`, `deleteRatio: 0`, `maxRetries: 0`.
- 600 request workers, 20 transports; the rate is shared across workers.
- WI opt-in and `schedulerName: kperf-admission-only`.
- `__RUN_NAMESPACE__` selects the run/attempt/rate namespace; `__PHASE_RUN_ID__`
  becomes `$(RUN_ID)-r<rate>` in the `benchmark-run` label. Cleanup uses that
  exact namespace for deletion, including its Pods and ServiceAccount; the label
  remains useful for identifying the phase's Pods.
- `payloadSize: 3650` pads an environment variable, not the complete submitted
  JSON. The resulting single-container Pod is approximately 4 KiB before
  server-side mutation/defaulting. The phase ownership label adds a small amount
  of metadata compared with the earlier unlabelled profile.

The existing installer extracts kperf from this pinned custom image:

```text
ghcr.io/liyu-ma/kperf@sha256:36f8e1cdbb6a4bd2fde4b29bf0cb5e4e014484ae9ddca9136f43449897ffb647
```

This is tag `sha-38567a6`, source commit
`38567a6b70337e7efa3d287988ab36cfe47f9d04` from
[Azure/kperf#260](https://github.com/Azure/kperf/pull/260). Replace the custom
image with an upstream release when available.

## Execution and results

For new clusters, the cluster-creation task installs `aks-preview` version `20.0.0b6` immediately
before `az aks create`. The extension provides `--control-plane-scaling-size H2`,
which the agent's base Azure CLI does not support.

The new-cluster path creates the cluster and worker pool. Both paths fetch
credentials into a temporary kubeconfig and install the pinned binaries. The
rate loop prepares each namespace and annotated ServiceAccount idempotently,
then generates profile, runner, namespace-deletion, and pause steps:

```text
prepare r50 namespace/ServiceAccount -> 50/sec for 10m -> request namespace deletion -> pause 5m
prepare r100 namespace/ServiceAccount -> 100/sec for 10m -> request namespace deletion -> pause 5m
prepare r150 namespace/ServiceAccount -> 150/sec for 10m -> request namespace deletion -> pause 5m
```

Each driver step invokes kperf directly, without a shared command wrapper:

```sh
kperf runner run --config "$profile" --kubeconfig "$kubeconfig"
```

[`common.RecordCurrentTime`](../lib/steps/common/record_current_time.k) records
one `BENCHMARK_START_TIME` after kperf installation and before the rate loop.
There are no per-rate timestamps or separately recorded end time.

After the loop, before resource-group deletion,
[`asi_dashboard.PrintAsiDashboardUrl`](../lib/util/asi_dashboard.k) prints
ASI Managed Cluster and API Server Analyzer URLs once, using
`$(BENCHMARK_START_TIME)` and the helper's current-time default for the end.
The links cover the overall benchmark window, including namespace preparation,
deletion requests, and recovery pauses, rather than individual rates.
The call uses the helper's default `always()` condition and `continueOnError`
behavior without a custom condition. URL-generation failures are reported but
do not fail the job; early setup failure can prevent a valid benchmark window.

There are no CLI traffic overrides, Kubernetes generator Jobs, smoke/warm-up
phases, manual-validation jobs, diagnostic collectors, or artifact uploads.
The native result JSON appears in normal ADO logs without result validation.
The resolved profile and kubeconfig live in
[`Agent.TempDirectory`](https://learn.microsoft.com/en-us/azure/devops/pipelines/build/variables?view=azure-devops#agent-variables-devops-services),
which ADO cleans after each job.

Each runner step has a 15-minute ADO timeout and no external timeout command.
ADO cancellation governs timeout handling.
Nonzero kperf process exits fail the step; no run is retried. Once a phase namespace
is successfully applied, deletion and the five-minute pause are attempted even
if ServiceAccount setup, profile preparation, or the driver fails; later rates
are skipped. A failed deletion command also blocks later rates, without skipping
the pause. Successfully requesting deletion does not require the namespace to
finish terminating before proceeding. HTTP errors in the
report do not independently fail it: kperf can exit zero despite failed requests,
as observed in build 84716. Missing or malformed reports are not checked.

The pinned runner's `total` is the configured request total, **not an observed
success count**; it remains zero for this duration-based run. Native duration
includes drain. Per-interval dispatch rates, actual WI invocation rates, and
inflight backlog are unavailable. This is exploratory traffic generation,
not proof that the webhook sustained the configured rate. Agent-to-API-server networking
also differs from an in-cluster driver.

## Prerequisites and cleanup

Operators ensure version/SKU availability, quota, and control-plane storage
headroom before queueing. Confirm no scheduler handles `kperf-admission-only`;
the benchmark Pods should remain unscheduled.

Successful traffic at each target would create approximately 30,000, 60,000,
and 90,000 Pods respectively before that phase's cleanup. The largest phase
is about 0.343 GiB of submitted JSON at 4 KiB each, before WI/defaulting,
revision history, and other storage overhead. There is no ResourceQuota,
continuous storage monitor, or manual storage gate.

Cleanup issues one namespace deletion request with `--wait=false` and
`--ignore-not-found=true`. It uses a 60-second API request timeout and a
15-minute ADO step limit, but never polls for namespace deletion completion.
Each 300-second pause has a six-minute step limit. The job allows 25 minutes
of cancellation grace for active cleanup and recovery where ADO permits.
Skipped phases do not perform cleanup or pause. A failed namespace apply does
not enable cleanup; inspect for partially created resources after such failures.

Namespace deletion may still be running after the pause and overlap the next
rate's traffic. Requesting deletion and pausing is not a full storage/cache reset:
etcd revisions, caches, controller state, and pre-existing objects remain.
Recovery and equivalent fresh-cluster baselines are not guaranteed.

`keep_cluster` defaults to **false**. For new clusters, the last step deletes the run's resource
group, including the cluster and its Prometheus workspace, even after a benchmark failure where
ADO permits cleanup. Creation uses `azure.CreateResourceGroup` directly.
Final deletion checks `USE_EXISTING_CLUSTER == 'false'` and `keep_cluster`,
without a separate resource-group ownership output or a `succeeded()` gate.
The mode starts as `unresolved`: reuse sets it to `true`, while new-cluster mode
becomes `false` only after the resource-group absence check succeeds. A failed
absence check or an existing-group collision
never authorizes deletion. Reused resource groups are **never deleted**, even when
`keep_cluster` is false or the benchmark fails.
Once the absence check passes, cleanup is attempted even if creation or a later
step fails. If creation never produced a resource group, the deletion command can
report that the resource group was not found.

With **true**, retain the cluster and Prometheus workspace, but still request
deletion of every prepared phase namespace and its ServiceAccount. With **false**,
deleting the group also deletes the workspace
and its stored metrics; export required results beforehand if historical
analysis is needed after cleanup. Existing-cluster reuse never deletes or
reconfigures its monitoring workspace.
Failed, interrupted, or still-pending namespace cleanup may leave some Pods behind.
Retained resources incur charges. Use the run's resource-group name from the
ADO logs for manual deletion when finished. There are no separate finalization
reports or deletion-verification steps. A hard agent interruption can prevent
cleanup; check Azure before assuming deletion completed.

## Development

`BenchmarkSteps(rate)` in [pipeline.k](./pipeline.k) returns the five per-rate
steps: WI setup, profile rendering, kperf execution, namespace deletion, and pause.
Cluster lifecycle, the overall start timestamp, and ASI reporting stay outside
the function.

```sh
kcl run kcl/workload_identity_webhook/pipeline.k -S output \
  -o kcl/workload_identity_webhook/pipeline.yaml
```

The pipeline does not install a Python
dependency bundle or use a custom Python orchestrator.

[ADO pipeline 94](https://dev.azure.com/akstelescope/telescope/_build?definitionId=94)
is registered as `Workload Identitiy Webhook Benchmark` under
`\AKS\Telescope\v2`, using `Azure/telescope:wi-web-bench` and
[pipeline.yaml](./pipeline.yaml). CI/PR triggers remain disabled.
Local changes do not affect that definition until pushed; do not queue a run
as part of local validation.
