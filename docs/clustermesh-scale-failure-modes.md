# ClusterMesh-on-AKS+Fleet failure-mode catalog

This catalog documents every observed failure mode in the
`clustermesh-scale` test pipeline, with machine-readable signatures so
retry logic and dashboards can detect, classify, and (where safe)
auto-recover.

**How to use:**
- Look up by **symptom signature** (log regex / metric pattern) to identify
  a failure from a new run.
- Read **root cause** to understand whether it's an Azure RP issue, a
  Cilium issue, a test harness issue, or a fundamental scale finding.
- Apply **mitigation** when running new builds (existing retry/fail-fast
  rules in `aks-cli/main.tf` consume some of these signatures).
- Use **linked builds** as historical evidence for the failure.

**Coverage matrix:** see the "What we TESTED vs what we did NOT" section
at the bottom for the explicit scope statement.

---

## Machine-readable signatures (consumed by retry logic)

| `id` | `error_regex` | `retryable` | `max_retry_budget_s` | `fail_fast_action` | `linked_builds` |
|---|---|---|---|---|---|
| `outbound_conn_fail_on_create` | `VMExtensionError_OutboundConnFail\|VMExtensionProvisioningError.*OutboundConnFail` | true (1 retry only) | 600 | abort + dump VMSS extension logs | 68700 |
| `prompool_already_exists` | `already exists` (in `az aks nodepool add` output) | true | 1800 | precheck state + recreate if Failed | 68577, 68700 |
| `subnet_referenced_resource_not_provisioned` | `ReferencedResourceNotProvisioned` | true | 1800 | retry after VNet PUT queue drains | 67775, 67788, 68700 |
| `aks_create_already_exists` | `already exists` (in `az aks create` output) | true | 600 | precheck state + delete if half-created | 67798 |
| `cluster_stuck_updating` | provisioningState=`Updating` for 30+ poll iterations w/ no state change | false (BRICKED) | n/a | abort immediately; cluster needs manual triage | 68577 (mesh-44) |
| `nodepool_stuck_failed_delete` | nodepool provisioningState=`Failed` AND `delete` call did not move state out of `Failed` within 120s | false (BRICKED) | n/a | abort immediately; nodepool needs manual delete | 69021 (mesh-50) |
| `fleet_cluster_id_zero_skip` | `cilium-config` ConfigMap `cluster-id=0` on a Fleet member | true | 1800 | delete + recreate `clustermeshprofile` (re-randomizes IDs) | 68035 |
| `acns_stuck_applying_non_euap` | `az fleet clustermeshprofile apply` hangs in `Applying` for >5min | false | n/a | abort; region does not have ACNS rolled out | (all westus2/canadacentral builds pre-2026-05-24) |
| `vmextension_error_k_*` | `VMExtensionError_K[A-Za-z]+` (kubelet/CRI failures) | false | n/a | abort + dump CSE logs; non-retryable | 68700 |

---

## Detailed entries

### `outbound_conn_fail_on_create`

**Symptom signature**
- Log regex: `VMExtensionError_OutboundConnFail` OR `VMExtensionProvisioningError.*OutboundConnFail`
- Metric pattern: AKS provisioningState transitions to `Failed` shortly after `az aks create` returns; agent log shows CSE script exit 50
- Wall-clock signature: failure within 5-10 min of `az aks create`

**Root cause**
- AKS VMSS provisioning runs a Custom Script Extension (CSE) at first boot to install kubelet/runtime packages
- Packages are downloaded from Microsoft package repos via outbound connectivity
- At N=100 shared-VNet, concurrent subnet PUT operations on the shared VNet keep some subnets in `Updating` state when their VMSS comes online
- Outbound NAT path uses a route that depends on the subnet being `Succeeded` → CSE script can't reach upstream → exit 50

**Mitigation (in code)**
- `aks-cli/main.tf` `aks_cli` retry block: when this error fires on retry iteration ≤2 AND on a fresh recreate (post our delete+recreate logic), allow ONE more retry with explicit partial-cluster cleanup. Past iteration 2, fail-fast.
- Not added to the general retryable regex — would mask real outbound config bugs at smaller N

**Manual recovery**
- Rerun the entire stage; new VNet provisioning order may avoid the race
- If recurs at N=100, consider lowering parallelism or splitting into multiple shared VNets

**Linked builds**
- 68700: 32 occurrences across the run; mesh-23 specifically died at attempt 3 of cluster recreate

---

### `prompool_already_exists`

**Symptom signature**
- Log regex: `The (agent pool|nodepool) .* already exists` (in `az aks nodepool add` stderr/stdout)
- Wall-clock signature: appears at apply retry boundary (i.e., terraform task attempt > 1)

**Root cause**
- Under `preserve_state_on_apply_failure=true` + AzDO `retryCountOnTaskFailure`, terraform may re-run the `local-exec` provisioner after a prior apply attempt already created the nodepool
- Without state precheck, `az aks nodepool add` returns "already exists" → script exits 1 → cycle repeats

**Mitigation (in code)**
- `aks-cli/main.tf` `aks_nodepool_cli` block (commit `bf99b8c`): state-aware precheck — Succeeded → exit 0; Creating/Updating/Deleting → wait; Failed → delete+recreate; absent → add. Plus "already exists" added to retryable regex.

**Linked builds**
- 68577 attempts 2 + 5 (deterministic bug)
- 68700 (absorbed cleanly by the fix — 707 already-exists hits, no failures)

---

### `subnet_referenced_resource_not_provisioned`

**Symptom signature**
- Log regex: `ReferencedResourceNotProvisioned`
- Often accompanied by: `Cannot proceed with operation because resource .* is not in Succeeded state. Resource is in Updating state and the last operation that updated/is updating the resource is PutSubnetOperation`

**Root cause**
- Azure VNet serializes all subnet PUT operations per-VNet (only one PutSubnetOperation in flight at a time)
- At N=100 shared-VNet with 200 subnets, concurrent AKS creates fan out subnet attach requests faster than Azure can serialize them
- AKS sees a peer cluster's subnet PUT mid-flight, rejects with this error

**Mitigation (in code)**
- `aks-cli/main.tf` `aks_cli` block: included in retryable regex. 15 retries × 60s = 15min budget; drains the queue.

**Linked builds**
- 67775, 67788: first observed at N=100
- 68700: 100+ retries absorbed cleanly

---

### `cluster_stuck_updating`

**Symptom signature**
- Metric pattern: AKS provisioningState=`Updating` for ≥30 consecutive 20s polls (10min) with no state change
- Log: `aks_wait_succeeded` emits same `provisioningState=Updating` line repeatedly with no transition

**Root cause**
- AKS Resource Provider regional queue stalls a cluster's reconciliation
- No external indicator of stuck vs slowly-progressing without ground-truth from RP team
- Build 68577 mesh-44 spent 30+ min stuck before being killed by AzDO retry; cluster was never recoverable

**Mitigation (in code)**
- `aks-cli/main.tf` `aks_wait_succeeded` (commit `716bf18`): track same-state count; if 30 consecutive polls observe the same state with no change, fail-fast immediately. Saves ~20min per occurrence.

**Linked builds**
- 68577 mesh-44 (4× internal retries × 30min each = 2+ hours wasted)

---

### `nodepool_stuck_failed_delete`

**Symptom signature**
- Metric pattern: nodepool provisioningState=`Failed` AND `az aks nodepool delete` API call returned but state remained `Failed` 120+ seconds later
- Log: `az aks nodepool delete reported error (will poll absence anyway)` followed by indefinite `still present (state=Failed)` polling

**Root cause**
- Azure RP rejected the delete (no transition to `Deleting`); the nodepool is bricked
- No amount of additional retries will release it without manual intervention

**Mitigation (in code)**
- `aks-cli/main.tf` `aks_nodepool_cli` block (commit `716bf18`): after issuing delete, if state still `Failed` 120s later (no Failed→Deleting transition), abort with clear `BRICKED` message. Saves ~88 of 90 minutes wasted on bricked nodepools.

**Linked builds**
- 69021 mesh-50 (13.6 HOURS burned on this exact pattern; the trigger for the fast-fail fix)

---

### `fleet_cluster_id_zero_skip`

**Symptom signature**
- After `az fleet clustermeshprofile apply` reports success, query
  `cilium-config` ConfigMap on a member → `cluster-id` value is `0`
- Cilium agent logs: errors about "invalid cluster ID 0"
- Cross-cluster traffic fails on the affected cluster

**Root cause**
- Fleet hash-allocation algorithm can collide on cluster IDs across mesh members
- When collision detected, one cluster gets ID 0 (skip-allocated) instead of a unique non-zero ID
- Mesh peering effectively skips this cluster

**Mitigation (in code)**
- `validate-resources.yml` detects ID=0 case → currently fails the stage
- Future: `cmp-auto-recovery` todo — delete + recreate `clustermeshprofile` (re-randomizes ID assignment, ~99% chance of resolving in one retry). Cost: ~15-30min vs ~3h for full pipeline rerun.

**Linked builds**
- 68035

---

### `acns_stuck_applying_non_euap`

**Symptom signature**
- `az fleet clustermeshprofile apply` returns success but state stays `Applying` indefinitely (>5min)
- No ACNS reconciler logs visible
- Region != `eastus2euap`

**Root cause**
- AKS-managed ClusterMesh / ACNS rollout was region-gated to eastus2euap pre-2026-05-24
- canadacentral verified working as of 2026-05-24
- Other regions (westus2, etc.) still gated as of that date

**Mitigation**
- Manual: only use regions verified to have ACNS rollout complete
- Code: no automated mitigation; fail-fast is correct behavior

**Linked builds**
- All westus2 builds pre-2026-05-24 (checkpoint 002 evidence)

---

### `vmextension_error_k_*`

**Symptom signature**
- Log regex: `VMExtensionError_K[A-Za-z]+` (e.g. `VMExtensionError_KubeletStart`)
- AKS provisioningState=`Failed` after CSE script reports kubelet/CRI startup failure

**Root cause**
- Kubelet or container runtime failed to start on the node
- Usually downstream of an earlier failure (disk full, OOM, image pull failure)
- Build 68700 saw 12 of these; root cause was the same shared-VNet outbound flux as `outbound_conn_fail_on_create`

**Mitigation**
- No automated retry — these usually indicate a real underlying problem
- Manual: check CSE logs (`/var/log/azure/cluster-provision-cse-output.log` on node) for the upstream cause

**Linked builds**
- 68700

---

## Covered / NOT-covered matrix (release scope statement)

### ✅ TESTED in current pipeline
- N=2/5/10/20/50/100 cluster meshes
- 4 `%global` cells: 0% / 20% / 60% / 100% of namespaces marked global
- 7 base scenarios: event-throughput, pod-churn-combined, isolation, node-churn-scale/replace/combined, upper-bound
- AKS-managed Cilium (current AKS version) + Fleet `clustermeshprofile`
- Single region: eastus2euap (canadacentral verified Fleet-capable but not yet sweeping)
- Shared-VNet topology (single VNet, 100 clusters share via subnet partition)
- pause-pod workloads (no real HTTP traffic in pre-2026-06-02 scenarios; propagation-probe.yaml adds real http-echo)

### ⚠️ PARTIALLY TESTED
- Global services (`service.cilium.io/global=true`): the Service objects ARE created in our scenarios but no client cross-cluster traffic exists. propagation-probe.yaml adds real cross-cluster curl.
- Synthetic propagation latency: kvstore_op_duration as proxy was used pre-2026-06-02; direct measurement added in propagation-probe.yaml.

### ❌ NOT TESTED (explicit gaps)
- **NetworkPolicy / CiliumNetworkPolicy at scale** — zero policies in any current scenario. See `policy-scale-matrix` todo.
- **L7 policies** (HTTP/Kafka/gRPC)
- **IPsec / WireGuard transparent encryption** between mesh peers
- **Mixed-version Cilium across mesh members** (version skew tolerance)
- **Cilium upgrade mid-mesh** (under load)
- **MCS-API (ServiceExport / ServiceImport)** as alternative to global services
- **Private clusters** (no public API endpoint)
- **Multi-region mesh** (cross-region latency, cross-region cost)
- **Mixed cluster sizes in same mesh** (small + large clusters together, fairness/QoS)
- **Pod density > 200 pods/cluster** — see `pod-density-scaling` todo
- **24h+ soak runs** — all current tests ≤ few hours. See `long-soak-test` todo.
- **Cluster loss / disaster recovery** — Fleet member permanently removed, mesh GC behavior. See `cluster-loss-recovery` todo.
- **CIDR overlap between clusters** (Cilium cluster_id disambiguation)
- **Bursty workload patterns** (10× spike then drop, vs sustained)
- **Hubble flow telemetry** (per-flow visibility into actual cross-cluster traffic)

This list is intentionally explicit so PMs/customers/operators know the
boundary of "tested at scale" claims. Items in NOT TESTED are not bugs —
they're scope choices for the current iteration.
