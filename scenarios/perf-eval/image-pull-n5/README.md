# Five image downloads from Kubernetes (Telescope V1)

[new-pipeline-test.yml](../../../pipelines/system/new-pipeline-test.yml) uses the same
V1 job framework as the [1,000-node ACR benchmark](../../../pipelines/perf-eval/ACR%20Benchmark/image-pull-n1000.yml):
provision AKS, validate resources, run a workload, publish results, and clean up.
It downloads `test1gb` **five times, once on each of five distinct real AKS workers**.

## Why the workload uses skopeo

On 2026-10-19, `test1gb:latest` resolved to the digest pinned in the pipeline. Its
manifest declares a single 1,073,741,824-byte gzip layer, but checking the first
1 KiB found neither a gzip nor a tar header. Its Linux/amd64 config specifies `sh`.
It is a synthetic registry-download artifact, not a suitable containerd
pull/unpack/start workload for the reference ClusterLoader2 startup test.

Each worker therefore runs the official `quay.io/skopeo/stable:v1.20.0` image and
executes one `skopeo copy --preserve-digests --retry-times 0` into a new `emptyDir`.
This transfers and verifies the original blob bytes without unpacking or executing
the target artifact. No target layers are shared between workers or cached from a
previous run. The helper image itself is pulled separately by Kubernetes.

**This measures Kubernetes-hosted ACR downloads, not native containerd image-pull
throughput or pod-startup latency.** ClusterLoader2/Prometheus settings and their
existing shared helpers are unchanged. To reproduce the native-runtime benchmark,
use a valid runnable image with the original image-pull topology.

## Target and infrastructure

- Registry: `williamjcusaue1.azurecr-test.io`, private Dogfood.
- Existing registry resource group: `rg_wj_cus1`; location: `australiaeast`.
- Test image: `test1gb:latest`, pinned by digest so all five downloads use the same
  content. Update `test_image` and this verification if the artifact changes.
- AKS: public Azure, in the pipeline's `AZURE_SUBSCRIPTION_ID`, **not** automatically
  the Dogfood registry subscription.
- [Terraform inputs](terraform-inputs/azure.tfvars) create `img-pull-5` in a new run-ID
  resource group: three system nodes and five workers, all `Standard_D4ds_v5`.
  **Eight VMs / 32 vCPUs** require sufficient regional and VM-family quota.
- AKS uses subnet `imgpull-subnet-1` (`10.0.0.0/16`) in `imgpull-vnet`
  (`10.0.0.0/9`). Its overlay pod CIDR is `10.128.0.0/9` and service CIDR is
  `192.168.0.0/16`; these ranges do not overlap. The AKS `subnet_name` must refer
  to the subnet, not the VNet, or the module falls back to a null subnet ID.
- Workers need access to Quay, the Dogfood registry, and its blob endpoints.

The pipeline does not create/delete `rg_wj_cus1`, enable anonymous registry access,
change registry role assignments, or attach the registry to AKS.

## Run

1. Commit/push the pipeline, scenario, and new topology templates to a test branch.
2. In the Telescope Azure DevOps pipeline pointing to
   `pipelines/system/new-pipeline-test.yml`, choose that branch.
3. Add `ACR_PULL_PASSWORD` as a **secret** pipeline variable. The username is
   configured as `williamjcusaue1`; use Docker-compatible pull credentials.
   Never commit the password.
4. Select the public-Azure subscription/service connection for AKS provisioning and
   queue manually. CI and PR triggers are disabled.
5. Read the `image-pull-<job-id>` artifact and normal Telescope result upload.

The runner creates a Secret via `kubectl` stdin and mounts it read-only in each
worker Pod. Credentials are not command arguments or result fields. Detailed
skopeo stderr stays in the temporary Pod volume because it could contain signed
redirect URLs; failures are reported explicitly without publishing those URLs.

All five Pods use `restartPolicy: Never`; the runner refuses Pod restarts and
requires five successful exits and valid metrics within 20 minutes. Failures and
timeouts fail the Azure DevOps job and are saved to the result artifact. The
namespace is deleted in `finally`, removing its Secret and per-pod downloads.
Standard V1 cleanup removes the new cluster and run-ID resource group.

Leave `SKIP_RESOURCE_MANAGEMENT` and `SKIP_RESOURCE_DELETION` unset. Forced agent
termination can interrupt cleanup; check for leftover run resources afterward.

## Results and scope

The result includes the pinned target, runner image, node placement, per-download
start/end times, duration, downloaded file bytes (layers plus config/manifest),
success count, pipeline URL, and errors. Timing starts after the helper container
starts, excluding its image download and cluster provisioning.

Pod creation is batched, but starts are not perfectly synchronized or aligned to a
five-minute boundary. There are five copy invocations; metadata requests and
transport-level retries mean this is **not exactly five HTTP requests**.
This test does not verify elastic-storage scale-out/scale-in. Query the storage
counters and replica status separately for those assertions.

## Offline tests

```powershell
python -m unittest discover -s scenarios\perf-eval\image-pull-n5 -p test_pull.py -v
```

Tests use the standard library and mock only the subprocess boundary. They do not
provision resources or download images.
