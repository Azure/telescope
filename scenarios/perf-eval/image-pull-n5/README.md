# Five layer downloads from one replica account (Telescope V1)

[new-pipeline-test.yml](../../../pipelines/system/new-pipeline-test.yml) provisions
five real AKS workers in Australia East and downloads the **same one-GiB layer
five times from one ACR-selected replica storage account**.

It retains the [reference benchmark's](../../../pipelines/perf-eval/ACR%20Benchmark/image-pull-n1000.yml)
V1 provisioning, results, and cleanup framework. It does not use ClusterLoader2
or measure native containerd image-pull/startup latency.

## Single-account guarantee

Normal registry pulls select a replica independently. Five `skopeo copy` calls can
therefore split their traffic between accounts and leave each account below the
scale-out threshold.

This scenario instead:

1. Starts one Python download worker on each of five distinct AKS nodes and waits
   until all workers are ready, excluding helper-image startup from the load window.
2. Authenticates to the registry and reads the pinned image manifest, verifying its
   SHA-256 digest and its single one-GiB layer descriptor.
3. Makes one authenticated registry blob request **without following the redirect**.
   The returned URL must be an HTTPS SAS URL for that layer on an eligible replica
   account (`replica` or `replstore` in its name).
4. Selects a future UTC-aligned five-minute window with at least three minutes for
   Kubernetes Secret-volume propagation. The SAS must remain valid through the
   whole window, with an additional 30-second margin.
   Before publishing the target, the coordinator checks that the entire window
   fits its remaining lifetime, including 275 seconds for result collection
   (six 45-second status/log-read timeouts plus a five-second polling allowance).
   Time spent starting workers and resolving the target counts against that budget.
   An infeasible schedule fails before any signed target is distributed.
5. Places that one signed URL and the common schedule in a temporary Kubernetes
   Secret. Every worker mounts the same Secret and downloads the exact same URL.
6. Verifies exactly 1,073,741,824 bytes and the layer SHA-256 digest on each worker.
   Redirects, range responses, retries, and account changes are not accepted.

The account is selected by ACR once per run; it is **not hardcoded to
`dfauereplica3` or `dfauereplica10`**. A later run can choose a different account.
If ACR returns a proxy/data-endpoint response instead of a direct Azure Storage
redirect, the test fails rather than silently falling back to random replica routing.

This is deliberately **five direct layer GETs**, not five independent full-image
pulls through the registry. Registry API logs show the metadata/redirect requests;
Azure Storage logs show the five full data transfers. The target layer is streamed
and hashed, not unpacked, executed, or retained on disk. It also works for the
synthetic `test1gb` artifact whose layer does not match its declared gzip format.

## Target and infrastructure

- Registry: `williamjcusaue1.azurecr-test.io`, private Dogfood.
- Existing registry resource group: `rg_wj_cus1`; location: `australiaeast`.
- Target: the pinned `test1gb` manifest in `test_image`. Its current layer is
  `sha256:f55fd51ca818223c1840e9521031ca779da8b29a4ceeda5d864f189e2bc9547d`.
- Worker image: official `python:3.12.12-slim`; Kubernetes pulls this separately.
- AKS: public Azure in the pipeline's `AZURE_SUBSCRIPTION_ID`, not automatically
  the Dogfood registry subscription.
- [Terraform inputs](terraform-inputs/azure.tfvars) create `img-pull-5` in a new
  run-ID resource group: three system nodes and five `Standard_D4ds_v5` workers.
  All eight nodes use that SKU: **8 VMs / 32 vCPUs**.
- AKS uses `imgpull-subnet-1` (`10.0.0.0/16`) in `imgpull-vnet` (`10.0.0.0/9`).
  Pod CIDR `10.128.0.0/9` and service CIDR `192.168.0.0/16` do not overlap.
- Agents need registry access; workers need access to Docker Hub and the selected
  Azure Storage blob endpoint.

No registry settings, feature flags, storage accounts, replicas, or `rg_wj_cus1`
resources are changed by the test.

## Configure and run

1. Commit/push the pipeline, scenario scripts, and renamed
   [topology templates](../../../steps/topology/image-pull-download) to your branch.
   The engine is now `blob-download`, not `skopeo`.
2. Set `ACR_PULL_PASSWORD` as a **secret** Azure DevOps pipeline variable for the
   configured username `williamjcusaue1`. Never store the password in YAML.
3. Run the existing pipeline pointing to `pipelines/system/new-pipeline-test.yml`
   with that branch. CI and PR triggers are disabled.
4. Leave `SKIP_RESOURCE_MANAGEMENT` and `SKIP_RESOURCE_DELETION` unset.
5. Inspect the `image-pull-<job-id>` artifact and normal Telescope results upload.

Only the coordinator uses registry credentials. Worker Pods receive a temporary,
blob-scoped SAS, not the registry password. Secrets are passed to Kubernetes over
stdin and never included in process arguments, public ConfigMaps, or result files.
HTTP errors are sanitized so signed URLs cannot leak into published diagnostics.
Kubernetes errors retain the operation, resource name when available, exit code or
timeout, and sanitized diagnostic text. Registry passwords, authorization tokens,
SAS signatures, and echoed Secret payloads are redacted.

The namespace is deleted in `finally`, removing the Secret, script ConfigMap, and
worker Pods. Standard V1 cleanup deletes the temporary cluster/run resource group.
Forced agent termination can interrupt cleanup; check for leftover run resources
after a forcibly stopped run.

## Success evidence

The result must contain:

- `status: "success"` and `successful_pulls: 5`.
- One top-level `storage_account`, `blob_digest`, `window_start`, and `window_end`.
- Five successful entries on distinct `node` values, each matching that account,
  digest, and window, with exactly `1073741824` downloaded bytes.
- Five distinct Azure `storage_request_id` values plus client request IDs for
  correlation with Kusto.
- Per-worker start/end timestamps entirely within the common five-minute window.

The worker validates content length and SHA-256, and makes only one storage GET
with no application retries. A wrong/expired URL, redirect, partial response,
hash mismatch, Pod restart, or out-of-window completion fails the run.
Both the worker and coordinator have a 20-minute timeout.
The Pod deadline uses the same lifetime setting. The coordinator starts its budget
before Pod creation, making it a conservative bound for all five Pod/worker
lifetimes. Each worker independently rejects a target window that exceeds its own
remaining lifetime.

If a worker fails, the coordinator first collects all terminal results in that
snapshot, then fails the run and cleans up. Completed peers retain their request
IDs, timings, and bytes; for example, four completed downloads and one failed worker
produce `successful_pulls: 4` with overall `status: "failure"`. Per-worker errors
also remain in the report. A malformed or unavailable log for one worker does not
prevent collecting the other workers' results.

Five successful layer GETs produce **5,368,709,120 bytes (5 GiB) on one account**.
That meets the checked-in elastic-storage test threshold when its comparison is
`>=` and the deployed settings match. The test does **not** assert scale-out
completion: verify the server-side counter, enabled flags, queue processing, and
replica status separately. Client UTC timestamps assume synchronized node clocks;
storage request timestamps and counters remain authoritative.

## Offline validation

```powershell
python -m unittest discover -s scenarios\perf-eval\image-pull-n5 -p "test_*.py" -v
```

Tests use Python's standard library and mock HTTP/subprocess boundaries, not live
cloud resources. Streaming tests hash a generated one-GiB response in small chunks
without allocating or writing a one-GiB file.
The local-launcher tests run on Linux (including WSL) and are skipped on Windows.

## Run locally from Windows

[run-local.ps1](run-local.ps1) runs five downloader Pods on **one local kind node**
inside WSL2 Ubuntu, using Podman. It does not use Azure DevOps or provision AKS.
The existing Azure pipeline still uses five distinct workers.

The Windows launcher enables **immediate starts**: the coordinator obtains one
signed target URL and creates the populated Secret before creating the five Pods.
Each Pod downloads as soon as its process starts and the initial volume is mounted.
There is no wait for a five-minute boundary, three-minute propagation allowance,
or later Secret-volume refresh. Kubernetes startup and registry authentication
still take time, and starts may be slightly staggered rather than simultaneous.

The five-minute **transfer deadline** remains, measured from target resolution;
Pod startup uses part of that budget. Byte/hash, account, expiry, failure, and
cleanup checks are unchanged. Local reports contain `start_mode: "immediate"`;
their `window_start`/`window_end` fields describe a client deadline, **not a
server-aligned accounting window**. Traffic can span server buckets, so five
successful downloads no longer ensure reaching a per-bucket scale-out threshold.
The Azure pipeline retains its original aligned start by default. Direct WSL
invocations of `local.py` can opt in with `--start-immediately`.

From the repository root in PowerShell:

```powershell
# Create/reuse the dedicated cluster and verify five Ready Pods without target traffic.
.\scenarios\perf-eval\image-pull-n5\run-local.ps1 -SetupOnly

# Perform one five-download run; enter the registry password/token at the hidden prompt.
.\scenarios\perf-eval\image-pull-n5\run-local.ps1
```

### Four concurrent downloads

```powershell
.\scenarios\perf-eval\image-pull-n5\run-local-four-pulls.ps1
```

[run-local-four-pulls.ps1](run-local-four-pulls.ps1) inherits the saved target
settings and password/prompt behavior from [run-local.ps1](run-local.ps1), but
creates exactly **four** downloader Pods on the local node. All four start
independently as soon as possible, with no aligned-window wait. It accepts the
same registry/image/username/password overrides. `-SetupOnly` verifies four
Ready Pods without downloading the layer.

A successful report has `expected_pulls: 4`, `successful_pulls: 4`, and four
per-Pod results: **4 GiB total** for this one-GiB layer. This exceeds the discussed
3-GiB warm threshold, but the still-warm test also depends on cooldown, account/window
totals, and server-side counters. Only four or five pulls are supported; three is
rejected. The usual single-batch launcher still defaults to five downloads and also
accepts `-PullCount 4`. The two-batch launcher remains five plus five and rejects
a four-download override.

### Two overlapping batches, one minute apart

To launch five downloads, then another five after one minute:

```powershell
.\scenarios\perf-eval\image-pull-n5\run-local-two-batches.ps1
```

[run-local-two-batches.ps1](run-local-two-batches.ps1) inherits the registry, image,
username, and password/prompt behavior from [run-local.ps1](run-local.ps1). It also
accepts the same per-run overrides and `-SetupOnly` (which checks readiness only).
The normal single-batch launcher still performs only five downloads by default.

The new launcher prepares the cluster once and starts two independent coordinators
60 seconds apart, **without waiting for the first batch to finish**. Each creates
five Pods, so up to ten downloads can overlap on the same node. These are ten
copies of the configured one-GiB layer, not ten different image references.
The delay is measured between coordinator launches; actual HTTP start times also
depend on registry authentication and Pod startup.

Batch namespaces are `acr-five-pulls-batch-1` and `acr-five-pulls-batch-2`, preventing
either batch from deleting the other's Pods. Each batch resolves its own ACR
redirect and has its own five-minute transfer deadline, so their selected storage
accounts may differ. Both reports must show `successful_pulls: 5` for ten verified
downloads overall. Reports use a shared run-ID prefix and `-batch-1.json` /
`-batch-2.json` suffixes in the usual WSL results directory.

The terminal remains attached until both batches finish; either batch failing
fails the command. Ctrl+C interrupts only these child coordinators so they can
clean up. Existing workload/batch namespaces are never silently reused or removed.
Do not start a separate launcher concurrently; the existing local lock covers
both batches. Two batches can generate 10 GiB and compete for the same bandwidth.

Edit the `Registry`, `Image`, and `Username` defaults at the top of
[run-local.ps1](run-local.ps1) to save a different target, or override them:

```powershell
.\scenarios\perf-eval\image-pull-n5\run-local.ps1 `
    -Registry "another.azurecr.io" `
    -Image "repository@sha256:<64-character-manifest-digest>" `
    -Username "pull-user"
```

The `Password` parameter defaults to the non-secret placeholder
`<REGISTRY_PASSWORD>`. Leaving it unchanged or empty preserves the hidden prompt.
A supplied value is passed to WSL through stdin, never in WSL command arguments;
`-SetupOnly` ignores it. Do not save real passwords in this file or terminal history.
Linux automation can supply `ACR_PULL_PASSWORD` or use `local.py --password-stdin`.
Credentials are not copied from the pipeline YAML. Rotate any exposed credentials
before reuse.

This preserves the scale-out test's constraints: the image must be a
digest-pinned, single-manifest image containing exactly one one-GiB layer, and
ACR must return an eligible Azure Storage replica URL. Tags, multi-layer images,
other layer sizes, and arbitrary non-ACR registries are not supported by this
specific test. These are direct layer downloads, not native image pulls.

The dedicated cluster is `acr-scaleout-local`. Its kubeconfig and timestamped
reports live under `~/.local/state/telescope-five-pulls` **in WSL Ubuntu**;
the launcher prints the exact report path. It never changes the default kubeconfig.
The local report has `node_count: 1`, `expected_pulls` matching the selected count,
and that many distinct Pods and storage request IDs on success. All Pods
intentionally share the node.

Each run creates fresh Pods and deletes the workload namespace afterward. The
local node is kept for the next run. `-SetupOnly` also removes its temporary
readiness-check Pods. A file lock prevents overlapping launcher runs; a leftover
workload namespace causes an explicit failure rather than deleting existing work.
Do not retry automatically after a partial failure: some traffic may already have
reached storage. Check `status`, `successful_pulls`, and each Pod's result.

After Windows/WSL restarts, kind may still list the cluster while its Podman node
container is stopped or back in `created` state. The launcher starts only its
expected node container before exporting kubeconfig, then waits up to three
minutes for API readiness. Already-running nodes are left running; unexpected
containers or paused/removing states fail explicitly. It does not delete or
recreate the cluster to recover from a stopped container.
Setup checks and actual downloads create a dedicated `acr-download` service
account before submitting Pods, avoiding the asynchronous default-service-account
creation race after startup. API token automounting remains disabled.

If you previously saw `can only create exec sessions on running containers`,
rerun `run-local.ps1 -SetupOnly` to recover and verify five Ready Pods without
downloading the target layer. Then run the launcher normally. A rootless Podman
`"/" is not a shared mount` warning alone is not that exec failure; do not change
system mount propagation or delete unrelated containers to address it.

Local requirements: Python 3.10+, kubectl, kind, Podman with cgroup v2 and a working
user systemd session in WSL2 Ubuntu. The first setup downloads the kind node and
Python helper images. All Pods share this machine's bandwidth; five GiB in 300
seconds requires roughly 143 Mbps of payload throughput plus headroom.
Storage counters and replica status must still be checked separately for scale-out.

To remove **only this dedicated local cluster**, from PowerShell:

```powershell
wsl --distribution Ubuntu --exec env KIND_EXPERIMENTAL_PROVIDER=podman kind delete cluster --name acr-scaleout-local
```
