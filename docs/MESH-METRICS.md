# ClusterMesh-scale snapshot metrics — reference

Explanations for the **mesh** metrics found in the local Prometheus snapshots
(`~/prom-snapshots/consolidated`, served at http://localhost:19000).

- **Cilium version in these snapshots:** `1.18.11` (from `cilium_kvstoremesh_version`).
- **Why Grafana's Metrics Explorer shows no descriptions:** this Prometheus serves
  imported TSDB blocks only — it never scraped live targets, so the metric
  metadata (HELP/TYPE) API is empty and Grafana has nothing to display on hover.
  **This is now fixed** for the metrics below: `mesh-metadata-exporter.py`
  (scraped as job `mesh-metadata`, port :19100) publishes their HELP/TYPE so the
  descriptions appear in Grafana. Its samples are zero-valued, tagged
  `snapshot_meta="1"`, and land at "now" — exclude them anywhere with
  `{snapshot_meta=""}` if needed. Started automatically by `start-all.sh`.

## How to look up any metric
1. **Cilium official reference** — https://docs.cilium.io/en/stable/observability/metrics/
   (sections *ClusterMesh* and *kvstoremesh*). Source of the HELP strings below.
2. **This repo's measurement configs** (best-commented, explains *why* each matters
   for scale) —
   `~/clustermesh-scale/telescope-upstream/modules/python/clusterloader2/clustermesh-scale/config/modules/measurements/`
   → `clustermesh-metrics.yaml`, `clustermesh-throughput.yaml`, `cilium.yaml`, `control-plane.yaml`.
3. **Naming convention** — `cilium_<subsystem>_<what>_<unit>`.
   Suffix `_total` = counter, `_bucket`/`_count`/`_sum` = histogram, otherwise gauge.

## Labels you'll see everywhere (added by the pipeline / Cilium)
- `snapshot_cluster` — the cluster whose Prometheus snapshot contained the
  sample (baked into native blocks so snapshots coexist safely).
- `source_cluster` — a metric-native Cilium label identifying the source
  cluster for that specific observation; it is never overwritten by snapshot
  relabeling.
- `target_cluster` — the **remote** peer a per-remote metric refers to.
- `scope` — kvstore data kind: `identities/v1`, `ip/v1` (endpoints), `services/v1`,
  `nodes/v1`, `serviceexports/v1`, plus internal (`cilium/.heartbeat`, `lease`, …).
- `job=cilium` (port `:9962`) = the **cilium-agent**; `job=monitoring/clustermesh-apiserver-*`
  (port `:9964`) = the **clustermesh-apiserver / kvstoremesh** sidecar.

---

## ClusterMesh — agent's view of remote clusters  (`job=cilium`, :9962)
| Metric | Type | Key labels | Meaning |
|---|---|---|---|
| `cilium_clustermesh_global_services` | gauge | `source_cluster` | Number of global (multi-cluster) services the agent knows about. |
| `cilium_clustermesh_remote_clusters` | gauge | `source_cluster` | Number of remote clusters meshed with the local cluster. |
| `cilium_clustermesh_remote_cluster_nodes` | gauge | `source_cluster`,`target_cluster` | Number of nodes seen in each remote cluster. |
| `cilium_clustermesh_remote_cluster_readiness_status` | gauge | `target_cluster` | Readiness of the remote-cluster connection (1 ready / 0 not). |
| `cilium_clustermesh_remote_cluster_failures` | gauge | `target_cluster` | Total failures related to the remote cluster. |
| `cilium_clustermesh_remote_cluster_last_failure_ts` | gauge | `target_cluster` | Unix timestamp of the last failure of the remote cluster. |

## kvstoremesh — the propagation engine  (`job=monitoring/clustermesh-apiserver-*`, :9964)
kvstoremesh mirrors each remote cluster's kvstore locally; these metrics are the
**cross-cluster propagation cost** signals.

### Remote-cluster state (same shape as above, from kvstoremesh's side)
| Metric | Type | Key labels | Meaning |
|---|---|---|---|
| `cilium_kvstoremesh_remote_clusters` | gauge | `source_cluster` | Remote clusters meshed, as seen by kvstoremesh. |
| `cilium_kvstoremesh_remote_cluster_readiness_status` | gauge | `target_cluster` | Readiness of each remote cluster (1/0). |
| `cilium_kvstoremesh_remote_cluster_failures` | gauge | `target_cluster` | Failures related to the remote cluster. |
| `cilium_kvstoremesh_remote_cluster_last_failure_ts` | gauge | `target_cluster` | Timestamp of the last remote-cluster failure. |

### Event & operation throughput / latency  ← the headline propagation metrics
| Metric | Type | Key labels | Meaning |
|---|---|---|---|
| `cilium_kvstoremesh_kvstore_events_queue_seconds_{count,sum,bucket}` | histogram | `scope`,`action` | Per-scope cross-cluster **event throughput** (`_count` rate = events/s) and time each event waited in the queue. The core propagation signal. |
| `cilium_kvstoremesh_kvstore_operations_duration_seconds_{count,sum,bucket}` | histogram | `scope`,`kind`,`action`,`outcome` | Latency of kvstore (etcd) operations — read/write/lease etc. Propagation op latency. |
| `cilium_kvstoremesh_kvstore_sync_queue_size` | gauge | `scope`,`source_cluster` | Elements queued waiting to sync — a **backlog** gauge; growing = saturation. |
| `cilium_kvstoremesh_kvstore_sync_errors_total` | counter | `scope`,`source_cluster` | Times a kvstore sync failed. |
| `cilium_kvstoremesh_kvstore_quorum_errors_total` | counter | `error` | etcd quorum errors. |
| `cilium_kvstoremesh_kvstore_initial_sync_completed` | gauge | `scope`,`source_cluster`,`action` | 1 once the initial full sync from/to the kvstore completed for that scope/cluster. |

### Startup / housekeeping
| Metric | Type | Key labels | Meaning |
|---|---|---|---|
| `cilium_kvstoremesh_bootstrap_seconds` | gauge | — | Duration to complete kvstoremesh bootstrap. |
| `cilium_kvstoremesh_controllers_group_runs_total` | counter | `group_name`,`status` | How many times each controller (reconcile) group ran, by success/fail. |
| `cilium_kvstoremesh_version` | gauge (=1) | `version`,`revision`,`arch` | Build info; value is 1, version is in the label (`1.18.11`). |

### API rate limiter (kvstoremesh → etcd)
| Metric | Type | Key labels | Meaning |
|---|---|---|---|
| `cilium_kvstoremesh_api_limiter_processed_requests_total` | counter | `api_call`,`outcome`,`return_code` | Total API/etcd requests processed. |
| `cilium_kvstoremesh_api_limiter_processing_duration_seconds` | gauge | `api_call`,`value` | Mean/estimated processing duration. |
| `cilium_kvstoremesh_api_limiter_wait_duration_seconds` | gauge | `api_call`,`value` | Time requests waited (throttled) before running. |
| `cilium_kvstoremesh_api_limiter_rate_limit` | gauge | `api_call`,`value` | Current rate-limit config (limit / burst). |
| `cilium_kvstoremesh_api_limiter_requests_in_flight` | gauge | `api_call`,`value` | Concurrent in-flight requests. |

### StateDB (Cilium's internal in-memory DB backing kvstoremesh)
| Metric | Type | Key labels | Meaning |
|---|---|---|---|
| `cilium_kvstoremesh_statedb_table_objects` | gauge | `table` | Number of objects in a StateDB table. |
| `cilium_kvstoremesh_statedb_table_graveyard_objects` | gauge | `table` | Deleted objects awaiting garbage collection. |
| `cilium_kvstoremesh_statedb_table_revision` | gauge | `table` | Current revision number of the table. |
| `cilium_kvstoremesh_statedb_table_contention_seconds_{count,sum,bucket}` | histogram | `table` | Time spent waiting on table locks (contention). |
| `cilium_kvstoremesh_statedb_write_txn_duration_seconds_{count,sum,bucket}` | histogram | `handle` | Duration of StateDB write transactions (by writer handle). |

## Feature flag
| Metric | Type | Meaning |
|---|---|---|
| `cilium_feature_adv_connect_and_lb_clustermesh_enabled` | gauge (0/1) | 1 when the ClusterMesh connectivity+LB feature is enabled. |

---

## Sample query per metric
One representative PromQL per metric (run in a snapshot window — see bottom).
A few return empty in a healthy window (no failures / all-ready); that's expected
and noted inline.

### ClusterMesh — agent (`job=cilium`, :9962)
```promql
max by (source_cluster) (cilium_clustermesh_global_services)                       # global services per cluster
max by (source_cluster) (cilium_clustermesh_remote_clusters)                       # peers per cluster (mesh fan-out)
sum by (source_cluster) (cilium_clustermesh_remote_cluster_nodes)                  # remote nodes seen per cluster
min by (source_cluster) (cilium_clustermesh_remote_cluster_readiness_status)       # 1 = all peers ready
max by (target_cluster) (cilium_clustermesh_remote_cluster_failures)               # failures per remote peer
max by (source_cluster, target_cluster) (cilium_clustermesh_remote_cluster_last_failure_ts)  # unix ts of last failure
```

### kvstoremesh — remote-cluster state (`job=…clustermesh-apiserver…`, :9964)
```promql
max by (source_cluster) (cilium_kvstoremesh_remote_clusters)                       # peers per cluster (kvstoremesh side)
min by (source_cluster) (cilium_kvstoremesh_remote_cluster_readiness_status)       # 1 = all remote links ready
max by (target_cluster) (cilium_kvstoremesh_remote_cluster_failures)               # failures per remote peer
max by (source_cluster, target_cluster) (cilium_kvstoremesh_remote_cluster_last_failure_ts)  # unix ts of last failure
```

### kvstoremesh — event/operation throughput & latency (the propagation signals)
```promql
sum by (scope) (rate(cilium_kvstoremesh_kvstore_events_queue_seconds_count[5m]))                       # cross-cluster event throughput (ev/s) by scope
histogram_quantile(0.99, sum by (le, scope) (rate(cilium_kvstoremesh_kvstore_events_queue_seconds_bucket[5m])))   # event queue-wait p99 by scope
histogram_quantile(0.99, sum by (le, action) (rate(cilium_kvstoremesh_kvstore_operations_duration_seconds_bucket[5m])))  # kvstore op latency p99 by action
max by (scope) (cilium_kvstoremesh_kvstore_sync_queue_size)                                            # sync backlog by scope
sum(rate(cilium_kvstoremesh_kvstore_sync_errors_total[5m]))                                            # sync error rate (0 when healthy)
sum(rate(cilium_kvstoremesh_kvstore_quorum_errors_total[10m]))                                         # etcd quorum errors (empty/0 when healthy)
min by (source_cluster) (cilium_kvstoremesh_kvstore_initial_sync_completed)                            # 1 = initial sync done for all scopes
```

### kvstoremesh — startup / housekeeping
```promql
max(cilium_kvstoremesh_bootstrap_seconds)                                                              # bootstrap duration (s)
sum by (group_name) (rate(cilium_kvstoremesh_controllers_group_runs_total{status="failure"}[5m]))     # failing reconciles/s (empty when none fail)
count by (version) (cilium_kvstoremesh_version)                                                        # which Cilium build (1.18.11)
```

### kvstoremesh — API rate limiter (→ etcd)
```promql
sum by (api_call, outcome) (rate(cilium_kvstoremesh_api_limiter_processed_requests_total[5m]))         # processed request rate by outcome
max by (api_call) (cilium_kvstoremesh_api_limiter_processing_duration_seconds{value="mean"})           # mean processing time (value: mean|estimated)
max by (api_call) (cilium_kvstoremesh_api_limiter_wait_duration_seconds{value="mean"})                 # mean throttle wait (value: min|mean|max)
max by (api_call) (cilium_kvstoremesh_api_limiter_rate_limit{value="limit"})                           # current limit (value: limit|burst)
max by (api_call) (cilium_kvstoremesh_api_limiter_requests_in_flight{value="in-flight"})               # in-flight requests (value: in-flight|limit)
```

### kvstoremesh — StateDB (internal in-memory DB)
```promql
sum by (table) (cilium_kvstoremesh_statedb_table_objects)                                              # objects per table
sum by (table) (cilium_kvstoremesh_statedb_table_graveyard_objects)                                    # deleted-pending-GC per table
max by (table) (cilium_kvstoremesh_statedb_table_revision)                                             # current table revision
histogram_quantile(0.99, sum by (le, table) (rate(cilium_kvstoremesh_statedb_table_contention_seconds_bucket[5m])))   # table lock contention p99
histogram_quantile(0.99, sum by (le, handle) (rate(cilium_kvstoremesh_statedb_write_txn_duration_seconds_bucket[5m])))  # write-txn duration p99 by handle
```

### Feature flag
```promql
max by (source_cluster) (cilium_feature_adv_connect_and_lb_clustermesh_enabled)                        # 1 = clustermesh feature enabled
```

---

## Documented in Cilium 1.18 but **NOT present** in these snapshots
(You pasted these from the docs; they don't appear in this data — either not emitted
by this build/config, or zero-valued and never scraped.)
- `cilium_clustermesh_remote_cluster_services` (per-remote service count; here only the aggregate `global_services` is present)
- `cilium_clustermesh_remote_cluster_endpoints`
- `cilium_clustermesh_remote_cluster_service_exports` (MCS-API)
- `cilium_clustermesh_remote_cluster_cache_revocations`
- `cilium_kvstoremesh_leader_election_master_status`

## Handy PromQL (from the pipeline's own measurements)
```promql
# Clusters reporting at an instant
count(count by (source_cluster) (cilium_clustermesh_global_services))

# Cross-cluster event throughput by scope (events/s)
sum by (scope) (rate(cilium_kvstoremesh_kvstore_events_queue_seconds_count[5m]))

# kvstore operation latency p50/p99 (propagation cost)
histogram_quantile(0.99, sum(rate(cilium_kvstoremesh_kvstore_operations_duration_seconds_bucket[5m])) by (le))

# Saturation: event backlog rate (sustained positive = draining slower than arriving)
sum(rate(cilium_kvstoremesh_kvstore_events_queue_seconds_count[1m]))
  - sum(rate(cilium_kvstoremesh_kvstore_sync_errors_total[1m]))

# Mesh fan-out: remote clusters per reporting cluster
sum by (source_cluster) (cilium_kvstoremesh_remote_clusters)
```

## Snapshot query windows (data is historical)
- propagation-probe run: `2026-06-18T01:05Z → 01:37Z`
- pod-churn n=100 run:   `2026-07-01T20:37Z → 2026-07-02T00:43Z`
