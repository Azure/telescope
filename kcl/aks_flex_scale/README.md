# AKS Flex Node 1,000-node join scale test

This Telescope scenario creates a public no-CNI AKS cluster, installs Unbounded,
creates a FlexNodes pool, pre-creates a private Ubuntu VM fleet, and then opens a
single authenticated storage gate to measure Flex joining independently from VM
allocation.

## Success contract

- Every configured VM must reach the preparation barrier before timing begins.
- All target ARM Machines must be `Succeeded`.
- All target Kubernetes Nodes must be Ready.
- Every target must obtain an approved exact-name daemon client CSR.
- The requirement is 100%; there is no partial-success threshold.
- The timed join phase is capped at 3,600 seconds.

Host/nspawn deep validation is represented in the result but intentionally deferred.

## Bootstrap modes

- `bootstrapMode=rp` uses the production-equivalent upstream `bootstrap.sh` flow
  with fresh AKS RP `listBootstrapData`.
- `bootstrapMode=local-config` is a temporary lab fallback based on the upstream
  `scripts/aks-flex-config` example. It creates run-scoped bootstrap RBAC and a
  four-hour Kubernetes bootstrap token, stores a base config only in the private
  gate container, and combines that token with the shared managed identity. Each
  VM injects its exact node name/private IP, runs preflight before the timed gate,
  and then invokes `aks-flex-node start` directly under the upstream-required `022`
  umask. This is important because restrictive rootfs path modes can make D-Bus
  inside systemd-nspawn hang. The config Blob is deleted after preparation and the
  token Secret is deleted after join success/failure.

Local config bypasses `listBootstrapData`. It explicitly sets
`agent.requireMachineRegistration=false`, following AKSFlexNode's `EnsureMachine`
behavior: an unsupported RP Machine operation is logged and bootstrap continues.
ARM Machine creation is therefore skipped as a success requirement in this temporary
mode and the result records that fact. `bootstrapMode=rp` continues to require every
ARM Machine to reach `Succeeded` and remains the production-equivalent scale result.

## Why the Flex subnet uses a NAT Gateway

Flex VMs have private IPv4 addresses and no public IPv4 addresses. VNet peering gives
private connectivity between the AKS and Flex VNets, but it does not provide internet
or transitive outbound connectivity. The Flex hosts still need outbound HTTPS for the
public AKS API, ARM/Entra, package preparation, and release artifacts. A subnet NAT
Gateway provides outbound-only IPv4 connectivity without opening inbound access to
individual VMs.

The NAT Gateway uses a `/28` Standard public-IP prefix so a 1,000-node burst does not
concentrate on one IP's SNAT port inventory. Agent, rootfs, and Kubernetes offline
bundle downloads use the IPv6-capable Azure Front Door endpoint documented by
AKSFlexNode operator-first-boot, rather than GitHub release downloads. VM package and
agent preparation happens before the timed gate; the result still records the exact
join interval separately from provisioning/preparation.

## Azure DevOps

Generate `pipeline.yaml` from `pipeline.k`, register it as a manual pipeline, and
supply the target subscription, regions, and a VM SKU with at least four vCPUs.
The default is 1,000 nodes. Use 10, 100, and 500 first to qualify a subscription.

The pipeline deletes both resource groups after success or failure by default. Set
`retainOnFailure=true` to retain a failed environment, or `retainEnvironment=true`
to retain the environment regardless of outcome while debugging. A retained run can
be resumed phase-by-phase with the same run ID and state directory.

## Local execution

Requirements:

- Python 3.10+
- Azure CLI authenticated to the target subscription
- `kubectl`, `curl`, `tar`, `jq`, `openssl`, and `ssh-keygen`
- Azure permissions to create the documented resources, role assignments, and
  register `PutMachinePreview`
- Quota for the requested fleet

Run an entire small qualification locally:

```bash
export PYTHONPATH="$PWD/modules/python"

python3 -m aks_flex_scale.cli all \
  --config kcl/aks_flex_scale/defaults.json \
  --state-dir .flex-scale-state/local-10 \
  --output result.json \
  --set runId=local-10 \
  --set subscriptionId='<subscription-id>' \
  --set aksRegion=canadacentral \
  --set vmRegion=canadacentral \
  --set flexVmSize=Standard_D4_v4 \
  --set nodeCount=10
```

Use `--retain` with `all` to keep resources regardless of outcome. Otherwise the
local all-in-one command follows `retainOnFailure` and deletes by default. For
iterative debugging, run phases separately and simply omit `cleanup`; `provision`
is idempotent for the same run ID, resource names, and state directory.

Every phase can also run separately and resumes from the same state directory:

```bash
COMMON="--config kcl/aks_flex_scale/defaults.json \
  --state-dir .flex-scale-state/local-10 \
  --set runId=local-10 \
  --set subscriptionId=<subscription-id> \
  --set aksRegion=canadacentral \
  --set vmRegion=canadacentral \
  --set flexVmSize=Standard_D4_v4 \
  --set nodeCount=10"

python3 -m aks_flex_scale.cli plan $COMMON
python3 -m aks_flex_scale.cli resolve $COMMON
python3 -m aks_flex_scale.cli preflight $COMMON
python3 -m aks_flex_scale.cli provision $COMMON
python3 -m aks_flex_scale.cli prepare-vms $COMMON
python3 -m aks_flex_scale.cli join $COMMON
python3 -m aks_flex_scale.cli validate $COMMON
python3 -m aks_flex_scale.cli result $COMMON --output result.json
python3 -m aks_flex_scale.cli cleanup $COMMON
```

Do not run `join` until all VMs have passed `prepare-vms`; opening the gate is
irreversible for that fleet. State and detailed events are stored in `state.json`
and `events.jsonl`.

## VM deployment strategy

VMs are generated as ARM templates in batches of 100. Each template contains 100
NICs and 100 VMs, while shared subnet NSG, identity, NAT, and storage resources are
created once. The default runs two batch deployments concurrently, producing ten ARM
deployments for 1,000 VMs instead of 1,000 `az vm create` deployments. This avoids
the resource-group deployment-history race encountered by the original implementation.
A failed batch is not retried: remaining waves stop and deletion of the run-specific
VM resource group is submitted while the AKS resource group is preserved.

## Current operational assumptions

- One shared user-assigned identity is attached to all Flex VMs.
- The synchronization gate uses a normal private Blob container. Account-level
  anonymous Blob access and static website hosting are disabled, and `$web` is
  explicitly forbidden. VMs authenticate with the shared managed identity, and
  the orchestrator uses its Azure identity with Blob data-plane RBAC. Storage
  account keys are not used.
- VMs have private NICs only.
- The default `/20` Flex subnet has sufficient headroom for 1,000 VMs.
- The default `/15` Flex pod CIDR covers 1,000 × 110 pod addresses.
- Latest stable releases are resolved once and recorded in run state. Explicit
  version overrides remain available when latest components are incompatible.
- Rootfs and offline artifact filename conventions are checked during qualification;
  release-specific names can be supplied through configuration overrides.
