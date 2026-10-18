# Five cold image pulls from Kubernetes

This manual Telescope V2 pipeline pulls `test1gb` concurrently on **five fresh,
real AKS worker nodes** in Australia East. It follows the Kubernetes/containerd
path used by the [February 2026 baseline test](https://msazure.visualstudio.com/AzureContainerRegistry/_git/acr-perf?path=/scenarios/acr-storage-performance/reports-Feb-2026-baseline/README.md&_a=preview),
not an image-copy tool running on the pipeline agent.

## Target and infrastructure

- Existing registry: `williamjcusaue1.azurecr-test.io`.
- Registry resource group: `rg_wj_cus1`, location: `australiaeast`.
- Registry cloud: Dogfood; subscription: `06f5e253-d825-4052-87ec-c4f12bc8f343`.
- Image: `test1gb:latest`, pinned in [pipeline.k](pipeline.k) to the digest resolved
  on 2026-10-18. Update the checked-in digest and regenerate YAML to test new content.
  The verified manifest contains one 1,073,741,824-byte (1 GiB) layer.
- AKS: public Azure, using the service connection and subscription in
  [lib/const.k](../../lib/const.k), not the Dogfood registry subscription.
- The pipeline creates a unique `acr-five-pulls-<run-id>` resource group containing
  one system node and five `Standard_D4ds_v5` worker nodes: **six VMs / 24 vCPUs**.
  Ensure regional and VM-family quota, subscription permissions, and network access.

The registry and `rg_wj_cus1` are never created, updated, or deleted. Cleanup only
targets the new test resource group, and only after its creation step succeeded.
An existing resource group with the generated name causes the run to fail rather
than reusing or deleting it.

## Configure and run

1. Use a Linux Azure DevOps agent with Azure CLI, `kubectl`, Python 3.10+, and
   `ssh-keygen`. The default pool is Telescope's `AKS-Telescope-Airlock`.
2. Authorize the configured public-Azure service connection to create/delete AKS,
   node pools, and resource groups and obtain the test cluster's kubeconfig.
3. The pipeline sets `ACR_PULL_USERNAME` to `williamjcusaue1`. In Azure DevOps,
   open the pipeline's **Edit > Variables**, add `ACR_PULL_PASSWORD`, select
   **Keep this value secret**, and save. The password must be a Docker-compatible
   credential for that username with pull access to `test1gb` on the Dogfood
   registry. Never put it in KCL or generated YAML. If switching to a short-lived
   or repository-scoped credential, update the username to match and regenerate
   YAML. Public-Azure AKS identity permissions do not automatically authorize
   access to this private Dogfood registry.
4. Generate the pipeline from the repository root:

   ```powershell
   Push-Location kcl\acr_benchmark\elastic_storage_five_pulls
   kcl run pipeline.k -S output -o pipeline.yaml
   Pop-Location
   ```

5. Push the source and generated YAML to your branch, register
   [pipeline.yaml](pipeline.yaml) as an Azure DevOps pipeline, and queue it manually.
   This scenario has no automatic CI or PR trigger.
6. Download the `acr-five-pulls` artifact and inspect `results.json`.

The runner places credentials in a temporary Kubernetes image-pull Secret via
`kubectl` stdin. Credentials are not command-line arguments, local credential
files, logs, or artifacts. The namespace is deleted after the test; the pipeline
also deletes its whole test resource group and removes its local SSH key and
kubeconfig. Forced agent termination can interrupt cleanup; check the run's
resource group if a job is forcibly stopped.

## Workload and success criteria

- Wait for exactly five Ready worker nodes, then submit five Pods in one batch.
- Bind each Pod to a different worker node, using the same immutable image digest.
  System nodes are not load generators. These are real workers, not KWOK nodes.
- Use `restartPolicy: Never` and a ten-minute Pod lifetime. **The image's default
  entrypoint executes** after download; this tests pulling, not application health.
  Containers are limited to 1 CPU / 1 GiB and removed once pull measurements finish.
- Require a `Pulling` and `Pulled` event for each Pod UID, reject cached-image events,
  and fail on observed image-pull errors or repeated pull attempts.
- Fail if five successful cold pulls are not observed within ten minutes.

Fresh nodes are the cold-cache guarantee; `imagePullPolicy: Always` alone does not
invalidate containerd's layer cache. The runner must not be reused against a warm
pool when comparing cold pulls. Native kubelet/runtime/network retries may occur
before observation, so **five Pods are not a guarantee of exactly five HTTP
requests**, nor are their start times an exact synchronization barrier.

The report includes the pinned image, node/runtime versions, per-pod outcome,
image ID when available, pull start/end timestamps, pull duration, successful-pull
count, pipeline URL, and errors. It records failures as well as successes and fails
the Azure DevOps job when a pull or namespace cleanup fails.

Timing comes from Kubernetes events and includes kubelet image-pull work, not
just wire transfer. This is not the V1 Prometheus/containerd throughput suite.
It also **does not assert elastic scale-out or scale-in**: five downloads do not
prove a per-blob, per-account, aligned five-minute egress threshold was crossed.
Verify storage counters, replica locations, and scaling status separately.

## Local validation

The runner uses only Python's standard library. Tests mock subprocess calls and
do not provision resources, access Azure, or pull images:

```powershell
python -m unittest discover -s kcl\acr_benchmark\elastic_storage_five_pulls -p test_pull.py -v
```
