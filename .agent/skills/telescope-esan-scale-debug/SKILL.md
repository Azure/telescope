---
name: telescope-esan-scale-debug
description: >
  Debug the Telescope Elastic SAN static-scale pipeline (kcl/ccp_team/elastic_san_static_scale)
  when large-scale provision or attach runs fail. Covers the two classes of failure seen at
  20K+ volume scale: (1) Azure Resource Manager 429 throttling during provision/attach
  (write throttle and List/read throttle), and (2) attach Pods stuck in Pending because the
  Elastic SAN CSI sidecar (csi-attacher) runs out of memory (OOMKilled). Use this skill when
  you see logs like "[arm-retry] GET status=429", "timed out waiting for N attached Pods",
  "FailedAttachVolume: timed out waiting for external-attacher", pods stuck Pending /
  ContainerCreating, OOMKilled on acstor-azuresan-csi-driver, or a node-capacity error like
  "N nodes required".
---

# Debugging the Elastic SAN static-scale pipeline

This pipeline provisions tens of thousands of static Azure Elastic SAN (iSCSI) volumes and
attaches one mount Pod per volume on an AKS cluster. Code lives in
`kcl/ccp_team/elastic_san_static_scale/` (`provision.py`, `attach.py`).

At scale, failures fall into three buckets. Identify which one from the log line, then follow
that section.

| Symptom in the log | Root cause | Section |
| --- | --- | --- |
| `[arm-retry] GET/PUT status=429 ...` (repeating) | ARM throttling (write or List/read) | A |
| `TimeoutError: timed out waiting for N attached Pods`, Pods stuck `Pending` | CSI `csi-attacher` OOM | B |
| `RuntimeError: ... N nodes required` | Not enough schedulable nodes | C |

Cluster used for the 160K benchmark (adjust for other environments):
`--subscription b8ceb4e5-f05b-4562-a9f5-14acb1f24219 --resource-group acstor-160k-sea --name aksacstor160ksea` (region `southeastasia`).

Get a read-only kubeconfig for any of the checks below:

```bash
KCFG=$(mktemp)
az aks get-credentials --subscription <sub> --resource-group <rg> --name <cluster> \
  --file "$KCFG" --overwrite-existing --only-show-errors
export KUBECONFIG="$KCFG"
```

---

## A. ARM 429 throttling (provision or attach)

SanRP (Microsoft.ElasticSan) has **two independent throttle buckets**:

- **Write throttle** – creating SANs / volume-groups / volumes. Limited per subscription
  (~3600 writes/hour) plus a short burst window.
- **List / read throttle** – `List_ObservationWindow_00:05:00`, empirically about
  **100 List operations per 5 minutes**. This is what inventory hits, because listing a
  200-volume-group SAN is ~200 List calls.

### How the code already protects against it
- `HourlyWriteLimiter` paces writes (configurable via `--max-volume-writes-per-hour`,
  `--max-volume-writes-per-burst`, `--burst-window-seconds`).
- `ReadRateLimiter` paces List operations to stay under the 5-minute window
  (`LIST_RATE_LIMIT = 90` per `LIST_RATE_WINDOW_SECONDS = 300`). It is enabled in `attach.py`
  via `client.read_limiter = ReadRateLimiter()`.
- Every GET is retried up to `READ_RETRY_ATTEMPTS = 24` times honoring the `Retry-After`
  header, so a read can outlast a full 5-minute List window.

### What to do when you still see it
1. **A burst of `[arm-retry] GET status=429` during inventory is EXPECTED and harmless** for a
   large SAN (200 volume groups ≈ 200 List calls). Inventory is intentionally slow
   (~10–15 min) because it rides just under the List budget. Let it run; the attach stage
   timeout is 24h.
2. Do **not** lower the limiter values to "go faster" — that just trips the throttle harder.
3. If a NEW code path lists volumes without pacing, make sure it goes through
   `ArmClient.list_all` (which calls `read_limiter.acquire()`), not a raw request loop.
4. Only touch write pacing if you see repeated `PUT status=429`; raising
   `--max-volume-writes-per-hour` above the subscription limit will not help.

---

## B. Attach Pods stuck Pending — CSI `csi-attacher` OOM (most common at scale)

Symptom: `attach.py` prints `[attach] ... ready=<X> pending=<Y> expected=<Z>` and eventually
`TimeoutError: timed out waiting for <Z> attached Pods`. `ready` never reaches `expected`.

### Step 1 — split "Pending" into scheduling vs volume-mount

```bash
kubectl get pods -A -l telescope-workload=elastic-san-static-scale \
  --field-selector=status.phase=Pending -o json > /tmp/pending.json
python3 - <<'PY'
import json,collections
p=json.load(open('/tmp/pending.json'))['items']
uns=sum(1 for x in p if not x.get('spec',{}).get('nodeName'))
cc=collections.Counter()
for x in p:
    if x.get('spec',{}).get('nodeName'):
        for cs in x.get('status',{}).get('containerStatuses',[]) or [{}]:
            cc[(cs.get('state',{}).get('waiting') or {}).get('reason','?')]+=1
print('pending',len(p),'unscheduled',uns,'scheduled_waiting',dict(cc))
PY
```

- `unscheduled > 0` → it is a **scheduling / node-capacity** problem → go to section C.
- `scheduled_waiting {'ContainerCreating': ...}` → it is a **volume attach** problem → continue.

### Step 2 — confirm it is the attacher, and confirm OOM

```bash
# Warning events: expect FailedAttachVolume + BackOff(csi-attacher) + OOMKilling
kubectl get events -A --field-selector type=Warning -o json \
 | python3 -c 'import json,sys,collections;e=json.load(sys.stdin)["items"];print(collections.Counter(x.get("reason") for x in e).most_common(8))'

# Sidecar memory limits and csi-attacher restart/OOM counts on the CSI DaemonSet
kubectl -n kube-system get ds acstor-azuresan-csi-driver -o json \
 | python3 -c 'import json,sys;[print(c["name"],c.get("resources",{}).get("limits")) for c in json.load(sys.stdin)["spec"]["template"]["spec"]["containers"]]'
kubectl -n kube-system get pods -o json > /tmp/kp.json
python3 - <<'PY'
import json,collections
pods=[p for p in json.load(open('/tmp/kp.json'))['items'] if 'azuresan-csi-driver' in p['metadata']['name']]
rs=oom=0
for p in pods:
    for cs in p.get('status',{}).get('containerStatuses',[]):
        if cs['name']!='csi-attacher': continue
        rs+=cs.get('restartCount',0)
        if cs.get('lastState',{}).get('terminated',{}).get('reason')=='OOMKilled': oom+=1
print('driver_pods',len(pods),'attacher_restart_sum',rs,'pods_with_lastOOM',oom)
PY
```

Diagnosis is confirmed when you see: event `FailedAttachVolume: timed out waiting for
external-attacher of san.csi.azure.com`, many `BackOff` on container `csi-attacher`,
`OOMKilling` events, and a low `csi-attacher` memory limit (default was **500Mi**) with a high
`attacher_restart_sum` and many `pods_with_lastOOM`. Every OOM restart drops in-flight
`VolumeAttachment` work, so the tail of volumes never attaches.

### Step 3 — fix: raise the csi-attacher memory limit (persistent)

The CSI driver is managed by the Azure Container Storage extension named `acstor`, so a direct
`kubectl edit` gets reverted by the extension reconciler. Change it through the extension config
(helm values keys are camelCase: `csiAttacher`, `csiResizer`, `csiProvisioner`). Include the
resizer/provisioner values in the same call so they are not lost:

```bash
az k8s-extension update --cluster-type managedClusters \
  --subscription <sub> --cluster-name <cluster> --resource-group <rg> --name acstor \
  --config "csiDriverConfigs.azuresan-csi-driver.values.resources.csiAttacher.limits.memory=2Gi" \
  --config "csiDriverConfigs.azuresan-csi-driver.values.resources.csiAttacher.requests.memory=256Mi" \
  --config "csiDriverConfigs.azuresan-csi-driver.values.resources.csiResizer.limits.memory=2Gi" \
  --config "csiDriverConfigs.azuresan-csi-driver.values.resources.csiResizer.requests.memory=256Mi" \
  --config "csiDriverConfigs.azuresan-csi-driver.values.resources.csiProvisioner.limits.memory=1Gi" \
  --config "csiDriverConfigs.azuresan-csi-driver.values.resources.csiProvisioner.requests.memory=128Mi" \
  --yes --only-show-errors
```

This triggers a rolling restart of the whole CSI DaemonSet (one pod per node). Wait for it and
verify the new limit + a healthy attacher:

```bash
kubectl -n kube-system get ds acstor-azuresan-csi-driver \
  -o custom-columns='DESIRED:.status.desiredNumberScheduled,UPDATED:.status.updatedNumberScheduled,READY:.status.numberReady'
# re-run the Step 2 attacher check: attacher_restart_sum and pods_with_lastOOM should stay 0
```

### Step 4 — recover
- The already-Pending Pods **self-heal**: once the attacher stops OOMing it retries the
  outstanding `VolumeAttachment`s and Pending drains toward 0. Watch:
  ```bash
  kubectl get pods -A -l telescope-workload=elastic-san-static-scale \
    --field-selector=status.phase=Pending -o name | wc -l
  ```
- **Re-running the attach stage is idempotent** (server-side apply; already-attached handles are
  filtered out). It recreates only the missing Pods and waits for full convergence. Safe to run
  after the rollout completes.

Other sidecars can OOM the same way — the fix pattern is identical, just change the sidecar name
(`csiResizer`, `csiProvisioner`) and value.

---

## C. Not enough nodes (scheduling)

Symptom: `RuntimeError: node selector '<sel>' has <A> nodes with at least <P> free Pod slots
plus <H> headroom; <N> nodes required`.

Attach places one Pod per volume. Required nodes = `ceil(volumes / pods_per_node)`. A node
qualifies only if `allocatable.pods - already_scheduled - pod_slot_headroom >= pods_per_node`.

Fix, pick one:
- **Cap the run**: set `--attach-limit` (pipeline `attach_limit`) to `usable_nodes * pods_per_node`
  or less. `--attach-limit 0` means attach everything.
- **Add nodes**: `az aks nodepool scale ... --node-count <N>` to reach the required node count,
  then re-run with `attach_limit=0`.
- Raising `--pods-per-node` usually does **not** help: the qualifying-node filter also requires
  `free slots >= pods_per_node`, so a higher value can shrink the candidate set.

---

## Quick reference

```bash
# how many Elastic SAN volumes are wired into the cluster
kubectl get pv --no-headers | wc -l
kubectl get volumeattachment --no-headers | wc -l
# benchmark mount-pods and their state
kubectl get pods -A -l telescope-workload=elastic-san-static-scale -o json \
 | python3 -c 'import json,sys,collections;d=json.load(sys.stdin)["items"];print("total",len(d),collections.Counter(p["status"].get("phase") for p in d))'
```

- Pod label: `telescope-workload=elastic-san-static-scale` (plus `telescope-cluster=<sha256(uid)[:12]>`).
- Attach pins Pods to selected workload nodes via node label key `telescope-esan-attach`.
- Run the Python tests after any code change:
  `cd kcl/ccp_team/elastic_san_static_scale && <venv>/bin/python -m unittest test_elastic_san_static_scale`.
