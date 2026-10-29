# Workload Identity webhook benchmark

A manual, exploratory benchmark on a dedicated AKS Standard H2 cluster in
`westus2`, subscription `b8ceb4e5-f05b-4562-a9f5-14acb1f24219`.

The cluster has three `Standard_D2_v4` system nodes and three
`Standard_D8s_v5` worker nodes. One generator Job runs on the worker pool.
Benchmark Pods remain unscheduled and do not need worker Pod slots.
Webhook replicas and resources are not tuned by this pipeline.

## Custom load profile

[load-profile.yaml](./load-profile.yaml) is the source of truth:

- 600 Pod CREATEs/sec ceiling, 600-second generation window.
- `total: 0`, `deleteRatio: 0`, `maxRetries: 0`.
- 600 synchronous request workers and 20 transports, not 600/sec per worker.
- WI opt-in, a dedicated annotated ServiceAccount, run/phase labels, and
  `schedulerName: kperf-admission-only`.
- `payloadSize: 3650` pads an environment variable; it is **not** submitted
  JSON size. Metadata, defaulting, and WI mutation change object size.

The pipeline renders run identifiers, mounts the profile through a ConfigMap,
and invokes `/kperf runner run --config /etc/kperf/load-profile.yaml` without
CLI traffic overrides. Separate smoke and warm-up profiles reuse the same
Pod configuration without changing the measurement profile.

The pinned custom image is:

```text
ghcr.io/liyu-ma/kperf@sha256:67e4924b23d2aea35526479721dd83f9afe707685a6efafd60916423017479d4
```

This is the public Linux amd64 image published as `sha-8e8e961`, corresponding
to [Azure/kperf#260](https://github.com/Azure/kperf/pull/260) source commit
`8e8e9617073fa7f0a9a51789923afa96d4d90121`. It is an intentional custom-image
exception; replace it with an upstream release when available.

## Workflow and safety

1. Check Kubernetes 1.36 availability, SKU eligibility and regional/family
   vCPU quota. Provision the H2 cluster, worker pool, and user-assigned identity.
2. **Manual storage preflight:** before any load, inspect current H2 telemetry.
   Record the telemetry source, observation time, available storage, and
   approved safety margin in the ADO validation comments. Reject if unavailable.
   Confirm no installed scheduler handles `kperf-admission-only`.
3. Check six Ready nodes and expected SKUs. Create isolated runner credentials
   with namespace-scoped Pod-create permission. No administrator kubeconfig is
   mounted into the runner. The benchmark identity needs neither Azure role
   assignments nor a federated credential because no token exchange is tested.
4. Smoke-test three Pods; verify WI environment/projected token mutation,
   ownership, and unscheduled state. Warm up at 5/sec for 30 seconds.
5. Execute one measurement Job. `backoffLimit: 0` prevents retries, and a
   900-second outer deadline bounds startup, generation, and drain.
6. Collect results and diagnostics, then finalize according to `keep_cluster`.

There is **no ResourceQuota** and no claimed 400,000-Pod H2 limit. At the target,
measurement alone retains approximately 360,000 Pods: about 1.37 GiB of
submitted JSON at 4 KiB each, before mutation, history, events, and storage
overhead. Warm-up and outstanding requests add more. Available vCPU quota is
not proof of physical regional capacity or control-plane storage headroom.

The storage preflight is an agentless ADO manual-validation job, with timeout
set to reject. It is not an automated storage-byte monitor. This first version
has bounded execution, not the original design's full continuous telemetry
and safety-stop implementation. Managed webhook configuration and storage
signals may require ASI/control-plane access beyond `kubectl`; do not infer
their values from worker nodes or substitute defaults.

### Retention

`keep_cluster` defaults to **false**:

- **false:** collect/publish artifacts, then delete only the resource group
  whose run and pipeline-definition ownership tags match.
- **true:** retain the cluster, managed identity, namespaces, completed Jobs,
  and benchmark Pods for inspection. Attempt to suspend unfinished generators;
  Job deadlines remain the fallback if the agent/API is unavailable.

Retained resources incur charges. The finalization artifact prints their IDs
and an explicit `az group delete` command. Failed or canceled runs attempt
collection/finalization using `always()`; a hard agent interruption can still
prevent these steps. Check the pipeline and Azure before assuming cleanup
completed. A setup failure before resource-group creation needs no deletion;
ownership-check failures deliberately block deletion.

## Results and limitations

ADO publishes setup, benchmark, and finalization artifacts containing:

- Resolved profiles, pinned image, identity client ID (not credentials), cluster
  configuration, and before/after platform and admission configuration.
- Per-phase orchestration timestamps, Job status, logs, original kperf JSON,
  latency percentiles in seconds, and request error counts.
- Post-run retained-Pod counts and a small set of admitted Pod samples/sizes.
  Enumeration is paginated outside measurement; full 360,000-Pod bodies are
  neither accumulated in memory nor uploaded.
- Collection failures, retention decisions, and deletion verification.

The pinned runner's `aggregated.total` and per-spec `total` mirror the configured
total; duration-based runs report **0** there. They are **not successful-request
counts**. Preserve them as `runner_reported_total`; separately report observed
retained Pods. A timeout/error response can still have created a Pod, so these
counts are not interchangeable.

The runner reports duration including drain. It does not expose per-10-second
dispatch rates, inflight backlog, actual WI invocation rates, exact generation/
drain boundaries, or submitted-body sizes. Successful exploratory execution
does **not** prove sustained offered load of 600/sec. Reported request errors,
missing/invalid results, smoke failures, and deadlines fail the pipeline rather
than being retried or silently accepted.

## Development and registration

The scenario's Python scripts use the repository's existing PyYAML dependency.
Run focused checks after regenerating:

```sh
kcl run kcl/workload_identity_webhook/pipeline.k -S output \
  -o kcl/workload_identity_webhook/pipeline.yaml
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s kcl/workload_identity_webhook -p 'test_*.py' -v
```

Registration target:

- Organization/project: `https://dev.azure.com/akstelescope` / `telescope`.
- Folder: `\AKS\Telescope\v2`.
- Definition name: `Workload Identitiy Webhook Benchmark` (requested spelling).
- Source: `Azure/telescope`, branch `wi-web-bench`.
- YAML: [pipeline.yaml](./pipeline.yaml).
- Existing GitHub connection: `telescope (1)`.
- Azure connection: `Azure-for-Telescope-internal`.
- Agent pool: `AKS-Telescope-Airlock`.

Keep CI/PR triggers disabled and register with `--skip-first-run true`.
Registration does not queue a benchmark or create Azure resources.
