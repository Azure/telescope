# Workload Identity webhook benchmark

One manual ADO job provisions a dedicated AKS Standard H2 cluster, prepares
workload identity, and runs kperf **once, directly on the ADO agent**.

## Configuration

- Subscription: `b8ceb4e5-f05b-4562-a9f5-14acb1f24219`; region: `westus2`.
- System pool: three `Standard_D4_v4` nodes.
- Worker pool: three `Standard_D2s_v5` nodes, retained as requested but not used
  to host the traffic driver.
- OIDC and workload identity enabled; webhook resources/replicas are not tuned.
- A benchmark ServiceAccount annotated with dummy client ID
  `00000000-0000-4000-8000-000000000001`. This preserves `AZURE_CLIENT_ID`
  injection without provisioning a workload managed identity. No federated
  credential or Azure role assignment is needed: this admission-only workload
  does not perform token exchange. Use a real identity for token-exchange tests.

[load-profile.yaml](./load-profile.yaml) is the traffic configuration:

- 400 Pod CREATEs/sec ceiling, 600-second generation window.
- `total: 0`, `deleteRatio: 0`, `maxRetries: 0`.
- 600 request workers, 20 transports; the rate is shared across workers.
- WI opt-in and `schedulerName: kperf-admission-only`; the dedicated namespace identifies the run.
- `payloadSize: 3650` pads an environment variable, not the complete submitted
  JSON. The resulting single-container Pod is approximately 4 KiB before
  server-side mutation/defaulting.

The existing installer extracts kperf from this pinned custom image:

```text
ghcr.io/liyu-ma/kperf@sha256:67e4924b23d2aea35526479721dd83f9afe707685a6efafd60916423017479d4
```

This is tag `sha-8e8e961`, source commit
`8e8e9617073fa7f0a9a51789923afa96d4d90121` from
[Azure/kperf#260](https://github.com/Azure/kperf/pull/260). Replace the custom
image with an upstream release when available.

## Execution and results

The cluster-creation task installs `aks-preview` version `20.0.0b6` immediately
before `az aks create`. The extension provides `--control-plane-scaling-size H2`,
which the agent's base Azure CLI does not support.

The job creates the cluster and worker pool, installs the pinned binaries,
fetches credentials into a temporary kubeconfig, creates the namespace and
annotated ServiceAccount, and renders the run namespace into a temporary
profile. It invokes:

```sh
kperf runner run --config "$profile" --kubeconfig "$kubeconfig"
```

Execution uses the shared
[`kperf.RunKperfRunner`](../lib/steps/kperf/run_benchmark.k) step:

```kcl
kperf.RunKperfRunner(
    profilePath="$(KPERF_PROFILE)",
    kubeconfig="$(KUBECONFIG)") | {timeoutInMinutes = 15}
```

Only `profilePath` is required. Optional arguments:

- `kubeconfig`: omitted by default, letting kperf select its default kubeconfig
  (`$HOME/.kube/config` outside Kubernetes, or in-cluster configuration when detected).
  This pipeline still supplies its isolated kubeconfig explicitly.
- `resultPath`: omitted by default, so kperf prints its native JSON directly to
  stdout. If supplied, kperf writes to that file instead; the caller owns the file.

The helper only runs the command and propagates its exit code. It does not install
kperf, provision workload resources, parse results, capture output, or delete files.

There are no CLI traffic overrides, Kubernetes generator Jobs, smoke/warm-up
phases, manual-validation jobs, diagnostic collectors, or artifact uploads.
The native result JSON appears in normal ADO logs without result validation.
The resolved profile and kubeconfig live in
[`Agent.TempDirectory`](https://learn.microsoft.com/en-us/azure/devops/pipelines/build/variables?view=azure-devops#agent-variables-devops-services),
which ADO cleans after each job; the shared runner does not delete caller inputs.

The caller sets a 15-minute ADO step timeout; the helper has no process-timeout
parameter or external timeout command. ADO cancellation governs timeout handling.
Nonzero kperf process exits fail the step; no run is retried. HTTP errors in the
report do not independently fail it: kperf can exit zero despite failed requests,
as observed in build 84716. Missing or malformed reports are not checked.

The pinned runner's `total` is the configured request total, **not an observed
success count**; it remains zero for this duration-based run. Native duration
includes drain. Per-interval dispatch rates, actual WI invocation rates, and
inflight backlog are unavailable. This is exploratory traffic generation,
not proof that the webhook sustained 400/sec. Agent-to-API-server networking
also differs from an in-cluster driver.

## Prerequisites and cleanup

Operators ensure version/SKU availability, quota, and control-plane storage
headroom before queueing. Confirm no scheduler handles `kperf-admission-only`;
the benchmark Pods should remain unscheduled.

At the target, approximately 240,000 Pods could accumulate: about 0.916 GiB of
submitted JSON at 4 KiB each, before WI/defaulting, revision history, and other
storage overhead. There is no ResourceQuota, continuous storage monitor, or
manual storage gate. The timeout is not a storage-capacity guarantee.

`keep_cluster` defaults to **false**. The last step deletes the run's resource
group, including the cluster, even after a benchmark failure where
ADO permits cleanup. Deletion is gated on successful resource-group creation
in this job; an existing-group collision never authorizes deletion.

With **true**, retain the cluster and benchmark Pods for inspection.
Retained resources incur charges. Use the run's resource-group name from the
ADO logs for manual deletion when finished. There are no separate finalization
reports or deletion-verification steps. A hard agent interruption can prevent
cleanup; check Azure before assuming deletion completed.

## Development

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
