# VMAgent Konnectivity Scale Load Test

## Mission

**Increase the VMAgent platform-metrics scrape ceiling from 150 nodes to 5,000 nodes over konnectivity**, with a clear empirical understanding of the bottleneck profile at each scale increment (150 → 250 → 500 → 1,000), and a validated architectural path to 6,000 nodes.

**Current limit:** `vmagentMaximumNodeCount = 150` — above this threshold, VMAgent switches from full-mode (all overlay targets) to default mode (overlay targets dropped).

**Scaling dimensions under investigation:**

| Dimension | Formula | Example at 1,000 nodes |
|-----------|---------|----------------------|
| Connections/sec | nodes x targets_per_node / scrape_interval | 1,000 x 4 / 30s = 133 conn/s |
| Data volume/connection | ~50-200 KB uncompressed, ~5-25 KB gzip | ~1.7 MB/s compressed sustained |
| Pod density (cadvisor cardinality) | containers_per_node x ~25 series | 150 pods/node = ~3,750 series/node |

**Success criteria:** >99% scrape rate at 5,000 nodes, konnectivity dial p99 < 2s, automated test turnaround < 30 min.

---

## Overview

This load test validates the **VMAgent → Konnectivity tunnel → Dataplane** metrics scraping pipeline used in AKS production (full-mode monitoring). It deploys a fake control plane across two AKS clusters and verifies that VMAgent can reliably scrape metrics from dataplane targets through the konnectivity proxy tunnel, and remote-write them to a receiver.

The test scrapes real dataplane nodes across **two target categories**:

### Real Targets — `--real-targets`

Scrapes **real kubelet, cadvisor, kube-proxy, and azure-cns** endpoints on the actual DP cluster nodes:

| Role | Address | Port | Scheme | Auth | Series/node |
|------|---------|------|--------|------|-------------|
| real-kubelet | `nodeIP:10250` | `/metrics` | HTTPS | Bearer token | ~2,300 |
| real-cadvisor | `nodeIP:10250` | `/metrics/cadvisor` | HTTPS | Bearer token | ~37,700 |
| real-kubeproxy | `nodeIP:10249` | `/metrics` | HTTP | None | ~500 |
| real-azure-cns | `nodeIP:10092` | `/metrics` | HTTP | None | ~200 |

With 3 DP nodes this gives **3 nodes × 4 roles = 12 real targets**. This validates that the konnectivity pipeline works end-to-end with **production-grade metrics data** (real cardinality, real metric names, real response sizes).

### DaemonSet Targets (Always Active)

In addition to real targets, VMAgent **always** scrapes the following DaemonSet-level services running on DP nodes. These match the production scrape configs from the KCL manifests and validate that the konnectivity tunnel handles the full breadth of overlay targets:

| Job Name | Port | SD Role | Production Source | Description |
|----------|------|---------|-------------------|-------------|
| `localdns` | 9253 | `node` | `dataplane/localdns.k` | node-local-dns (CoreDNS) metrics — `coredns_cache_*`, `coredns_dns_request*`, `coredns_forward_*` |
| `node-problem-detector` | 20257 | `node` | `node_lifecycle/node_runtime/node-problem-detector.k` | NPD metrics — `problem_counter`, `disk_avg_queue_len`, `disk_weighted_io` |
| `csi-azuredisk-node` | named `metrics` | `pod` (kube-system) | `csi_storage/disk/csi_azuredisk_driver.k` | Azure Disk CSI node driver — `azuredisk_csi_driver_operation_duration_seconds*` |

These jobs use the same `proxy_url` → konnectivity tunnel path as all other scrape jobs. If localdns or NPD is not running on the DP cluster, the jobs are simply idle (no matching targets via SD).

**Scrape path under test (real targets — HTTPS):**

> **VMAgent** → **vmagent-proxy** `do_CONNECT` (HTTPS tunnel, bidirectional byte relay) → **Konnectivity Server** (mTLS tunnel) → **Konnectivity Agent** → **Real kubelet/cadvisor/kube-proxy** (TLS + bearer token auth end-to-end)

**Scrape path under test (DaemonSet targets — HTTP):**

> **VMAgent** → **vmagent-proxy** `do_GET` → **Konnectivity Server** → **Konnectivity Agent** → **localdns :9253 / NPD :20257 / azuredisk-node pod**

**Remote write path under test:**

> **VMAgent** → **VMSingle** (POST /api/v1/write) — validates that scraped samples are persisted and queryable via PromQL

**Key goals:**
- Validate scrape reliability against real dataplane targets (kubelet/cadvisor/kube-proxy/azure-cns) through the konnectivity tunnel
- Measure konnectivity dial latency, stream throughput, and connection metrics
- Verify the remote write pipeline end-to-end
- Validate DaemonSet targets (localdns, NPD, azuredisk-node) matching production scrape configs
- Collect pprof profiles from all key components for bottleneck analysis
- Automated pass/fail with JSON results

---

## Architecture

::: mermaid
graph TB
    subgraph DEVBOX["Test Runner - devbox"]
        PY["main.py<br/>Deploy, Generate mTLS certs<br/>Poll targets 30s, Collect metrics<br/>pprof profiling, Pass/Fail + JSON"]
    end

    subgraph CP["CONTROL PLANE CLUSTER - fakecpcluster"]
        subgraph CPNS["loadtest-N namespace"]
            subgraph VAPOD["VMAgent Pod"]
                VA["VMAgent :8429<br/>30s scrape interval<br/>stream_parse: true<br/>kubernetes_sd_configs<br/>7 scrape jobs"]
                PROXY["vmagent-proxy :8080<br/>do_GET → HTTP targets<br/>do_CONNECT → HTTPS targets<br/>chunked decode via<br/>http.client.HTTPResponse"]
            end
            SINGLE["VMSingle :8428<br/>Remote write receiver<br/>PromQL queryable"]
            KS["Konnectivity Server<br/>:8081 agent gRPC<br/>:8083 mTLS CONNECT<br/>:8096 admin/pprof<br/>LoadBalancer IP"]
            CERT1["konnectivity-certs<br/>ca + server + client"]
            TOKEN["kubelet-scrape-token<br/>(SD + kubelet auth)"]
        end
    end

    subgraph DP["DATAPLANE CLUSTER - fakedpcluster"]
        subgraph DPNS["loadtest-N namespace"]
            KA["Konnectivity Agents<br/>N replicas<br/>gRPC to server<br/>mTLS client certs<br/>:8094 admin/pprof"]
            SA["kubelet-scraper SA<br/>+ ClusterRoleBinding<br/>(SD + kubelet auth)"]
            CERT2["konnectivity-certs<br/>ca + client"]
        end
        subgraph REAL["Real Node Endpoints<br/>(real-targets mode only)"]
            RK["kubelet :10250<br/>HTTPS + bearer token<br/>~2,300 series/node"]
            RC["cadvisor :10250<br/>/metrics/cadvisor<br/>~37,700 series/node"]
            RP["kube-proxy :10249<br/>HTTP, no auth<br/>~500 series/node"]
            RCNS["azure-cns :10092<br/>HTTP, no auth<br/>~200 series/node"]
        end
        subgraph DAEMON["DaemonSet Targets<br/>(always active)"]
            LD["localdns :9253<br/>coredns_* metrics"]
            NPD["node-problem-detector :20257<br/>problem_counter, disk_*"]
            AZD["csi-azuredisk-node<br/>kube-system pod<br/>azuredisk_csi_driver_*"]
        end
    end

    VA -->|"scrape jobs via proxy_url"| PROXY
    PROXY -->|"do_GET: mTLS CONNECT :8083"| KS
    PROXY -->|"do_CONNECT: HTTPS tunnel :8083"| KS
    KS -->|"gRPC stream to agent"| KA
    KA -->|"TCP forward (real HTTPS)"| RK
    KA -->|"TCP forward (real HTTPS)"| RC
    KA -->|"TCP forward (real HTTP)"| RP
    KA -->|"TCP forward (real HTTP)"| RCNS
    KA -->|"TCP forward (daemon HTTP)"| LD
    KA -->|"TCP forward (daemon HTTP)"| NPD
    KA -->|"TCP forward (daemon HTTP)"| AZD

    VA -->|"Remote Write POST /api/v1/write"| SINGLE

    VA -.->|"kubernetes_sd_configs<br/>role:pod / role:node"| DP

    KA -.->|"gRPC :8081 via LB public IP"| KS

    PY -.->|"kubectl apply"| CP
    PY -.->|"kubectl apply"| DP
    PY -.->|"port-forward :8429 pprof"| VA
    PY -.->|"port-forward :8096 pprof"| KS
    PY -.->|"port-forward :8094 pprof"| KA
    PY -.->|"port-forward + query"| SINGLE

    style DEVBOX fill:#f3e8ff,stroke:#7c3aed,stroke-width:2px,color:#1e1b4b
    style PY fill:#ede9fe,stroke:#7c3aed,color:#1e1b4b
    style CP fill:#eff6ff,stroke:#2563eb,stroke-width:2px,color:#1e3a5f
    style CPNS fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
    style VAPOD fill:#c7d2fe,stroke:#6366f1,color:#1e1b4b
    style VA fill:#a5b4fc,stroke:#4f46e5,color:#1e1b4b
    style PROXY fill:#a5b4fc,stroke:#4f46e5,color:#1e1b4b
    style SINGLE fill:#bae6fd,stroke:#0284c7,color:#0c4a6e
    style KS fill:#bbf7d0,stroke:#16a34a,color:#14532d
    style CERT1 fill:#fef3c7,stroke:#d97706,color:#78350f
    style TOKEN fill:#fef3c7,stroke:#d97706,color:#78350f
    style DP fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#14532d
    style DPNS fill:#dcfce7,stroke:#22c55e,color:#14532d
    style REAL fill:#dbeafe,stroke:#2563eb,color:#1e3a5f
    style DAEMON fill:#fef9c3,stroke:#ca8a04,color:#713f12
    style KA fill:#bbf7d0,stroke:#16a34a,color:#14532d
    style SA fill:#fef3c7,stroke:#d97706,color:#78350f
    style RK fill:#bfdbfe,stroke:#2563eb,color:#1e3a5f
    style RC fill:#bfdbfe,stroke:#2563eb,color:#1e3a5f
    style RP fill:#bfdbfe,stroke:#2563eb,color:#1e3a5f
    style RCNS fill:#bfdbfe,stroke:#2563eb,color:#1e3a5f
    style LD fill:#fef08a,stroke:#ca8a04,color:#713f12
    style NPD fill:#fef08a,stroke:#ca8a04,color:#713f12
    style AZD fill:#fef08a,stroke:#ca8a04,color:#713f12
    style CERT2 fill:#fef3c7,stroke:#d97706,color:#78350f
:::

### Updated topology — Option A (direct HTTPS CONNECT) + multi-nodepool fan-out

_Added 2026-07-07. HTTPS targets (kubelet/cadvisor) now bypass the Python proxy and CONNECT straight to konnectivity-server via `proxy_tls_config`; dataplane fans out across `dataplane`, `dataplane2`, ... (≤1000 nodes each) past the AKS per-nodepool cap. See **HTTPS-Direct-CONNECT-and-Multi-Nodepool-Scaling** for details._

::: mermaid
graph TB
    subgraph CP["Control Plane (underlay)"]
        VA["VMAgent :8429<br/>N native-clustering shards"]
        PROXY["vmagent-proxy :8080<br/>HTTP targets only (pooled)"]
        KS["Konnectivity Server :8083<br/>http-connect proxy"]
    end
    subgraph DP["Dataplane real nodes (fanned across pools)"]
        P1["nodepool dataplane (<=1000)<br/>konn-agents + kubelet/cadvisor :10250"]
        P2["nodepool dataplane2 (<=1000)<br/>konn-agents + kubelet/cadvisor :10250"]
    end
    VA -->|"HTTP: proxy_url :8080"| PROXY
    PROXY -->|"pooled CONNECT :8083"| KS
    VA ==>|"HTTPS: DIRECT CONNECT :8083 (proxy_tls_config)"| KS
    KS -->|gRPC| P1
    KS -->|gRPC| P2
    style VA fill:#a5b4fc,stroke:#4f46e5
    style KS fill:#bbf7d0,stroke:#16a34a
:::


### Data Flow

| Step | From | To | Description |
|------|------|----|-------------|
| 1 | VMAgent | vmagent-proxy | HTTP GET via `proxy_url` (localhost:8080), for HTTP jobs (real-kubeproxy, real-azure-cns, localdns, NPD, azuredisk-node) |
| 2 | VMAgent | vmagent-proxy | HTTPS CONNECT via `proxy_url` (localhost:8080), for HTTPS jobs (real-kubelet, real-cadvisor) |
| 3a | vmagent-proxy (`do_GET`) | Konnectivity Server | mTLS CONNECT tunnel on port 8083, sends HTTP GET through tunnel, chunked response decoded by `http.client.HTTPResponse` |
| 3b | vmagent-proxy (`do_CONNECT`) | Konnectivity Server | mTLS CONNECT tunnel on port 8083, bidirectional byte relay (opaque TLS passthrough) |
| 4 | Konnectivity Server | Konnectivity Agent | gRPC stream forwards request to agent on dataplane |
| 5a | Konnectivity Agent | real kubelet | TCP forward to nodeIP:10250, TLS + bearer token end-to-end |
| 5b | Konnectivity Agent | real cadvisor | TCP forward to nodeIP:10250/metrics/cadvisor, TLS + bearer token |
| 5c | Konnectivity Agent | real kube-proxy | TCP forward to nodeIP:10249 (plain HTTP) |
| 5d | Konnectivity Agent | real azure-cns | TCP forward to nodeIP:10092 (plain HTTP) |
| 5e | Konnectivity Agent | localdns | TCP forward to nodeIP:9253 (plain HTTP, always active) |
| 5f | Konnectivity Agent | NPD | TCP forward to nodeIP:20257 (plain HTTP, always active) |
| 5g | Konnectivity Agent | azuredisk-node | TCP forward to podIP:metrics (plain HTTP, always active) |
| 6 | VMAgent | VMSingle | Remote write POST `/api/v1/write` (validates write path) |

### Target Discovery

All scrape jobs use **`kubernetes_sd_configs`** for dynamic target discovery against the DP cluster API server — no hardcoded IP addresses:

| Job Type | SD Role | Namespace Filter | Address Relabeling |
|----------|---------|-----------------|-------------------|
| Real target jobs | `role: node` | (all nodes) | `__meta_kubernetes_node_address_InternalIP` → `nodeIP:port` |
| localdns | `role: node` | (all nodes) | `nodeIP` → `:9253` |
| node-problem-detector | `role: node` | (all nodes) | `nodeIP` → `:20257` |
| csi-azuredisk-node | `role: pod` | `kube-system` | `podIP:metrics` (container port name filter) |

VMAgent's SD requests go **directly** to the DP API server (not through konnectivity), while actual scrape requests go through the konnectivity tunnel via `proxy_url`.

The DP API server URL is auto-detected from the DP kubeconfig and injected as the `__DP_API_SERVER__` template variable. A `kubelet-scraper` ServiceAccount token is used for both SD authentication and kubelet bearer token auth.

### vmagent-proxy: Dual-Mode Proxy

The vmagent-proxy sidecar supports **two request handlers**:

| Handler | When Used | Flow |
|---------|-----------|------|
| `do_GET` | Real HTTP targets (kube-proxy, azure-cns), DaemonSet targets (HTTP) | Receives `GET http://podIP:port/metrics`, opens mTLS CONNECT tunnel to konnectivity, sends GET through tunnel, decodes chunked response via `http.client.HTTPResponse`, returns to VMAgent |
| `do_CONNECT` | Real targets (HTTPS) | Receives `CONNECT nodeIP:10250`, opens mTLS CONNECT tunnel to konnectivity, returns `200 Connection Established`, then does **bidirectional byte relay** (`select.select` loop) — VMAgent handles TLS + auth end-to-end through the tunnel |

### Real-Targets RBAC Setup

When `--real-targets` is used, the test automatically:

1. Creates a `kubelet-scraper` ServiceAccount in the DP loadtest namespace
2. Creates ClusterRoleBindings granting `system:kubelet-api-admin` (nodes/metrics, nodes/proxy, nodes/stats) and `view` (for SD pod/node listing)
3. Generates a 2-hour token via `kubectl create token`
4. Transfers the token to the CP cluster as a Secret (`kubelet-scrape-token`)
5. VMAgent mounts the token at `/var/run/secrets/kubelet/token` and uses it for both `kubernetes_sd_configs` and `authorization.credentials_file`

---

## Why VMSingle Instead of vmagent-metric-receiver

AKS production uses a **`vmagent-metric-receiver`** sidecar (`mcr.microsoft.com/aks/hcp/vmagent-metric-receiver`) that runs alongside vmagent in E2E environments. It accepts Prometheus remote write on port 8280 and validates that required metrics arrive via a `/healthz` endpoint.

We use **VMSingle** instead because the load test needs capabilities the receiver doesn't provide:

| Capability | VMSingle | vmagent-metric-receiver |
|-----------|----------|------------------------|
| Accepts remote write | :white_check_mark: `/api/v1/write` on :8428 | :white_check_mark: `/api/v1/write` on :8280 |
| PromQL queries | :white_check_mark: `count(up)` to verify series count | :x: No query engine |
| Cadvisor container queries | :white_check_mark: Query konnectivity-agent CPU/memory from cadvisor data | :x: No query engine |
| Write-path metrics | :white_check_mark: `vm_rows_inserted_total`, `vm_http_errors_total` | :x: Only `/healthz` pass/fail |
| Required metrics check | :x: (not needed, we count targets) | :white_check_mark: ConfigMap-driven `/healthz` |
| Data persistence | :white_check_mark: Full TSDB, queryable after soak | :x: Receives and discards |

The load test relies on PromQL to:
1. **`count(up)`** — verify the exact number of UP series matches expected targets
2. **Cadvisor container metrics** — query `container_cpu_usage_seconds_total` and `container_memory_working_set_bytes` for konnectivity-agent pods from data VMAgent scraped and wrote to VMSingle
3. **Write-path validation** — confirm `vm_rows_inserted_total > 0` and `vm_http_errors_total == 0`

These are part of the automated pass/fail criteria. The vmagent-metric-receiver only answers "did I see metric X?" via `/healthz`, which is insufficient for quantitative scale analysis.

---

## Infrastructure Setup

### Prerequisites

- Azure subscription with permissions to create AKS clusters
- `az`, `kubectl`, `python3` installed on devbox
- `cryptography` Python package (for TLS cert generation — no cfssl needed)
- `go` installed (for pprof analysis via `go tool pprof`)
- Two AKS clusters in the same region (or peered VNets)

### Create AKS Clusters

```bash
# Resource group
az group create --name VMAgent-Load-testing --location westus2

# Control plane cluster
az aks create \
  --resource-group VMAgent-Load-testing \
  --name fakecpcluster \
  --node-count 3 \
  --node-vm-size Standard_D2ds_v5 \
  --generate-ssh-keys

# Dataplane cluster
az aks create \
  --resource-group VMAgent-Load-testing \
  --name fakedpcluster \
  --node-count 3 \
  --node-vm-size Standard_D2ds_v5 \
  --generate-ssh-keys

# Get kubeconfigs
az aks get-credentials --resource-group VMAgent-Load-testing \
  --name fakecpcluster --file /tmp/fakecpcluster.kubeconfig
az aks get-credentials --resource-group VMAgent-Load-testing \
  --name fakedpcluster --file /tmp/fakedpcluster.kubeconfig
```

### Component Images

| Component | Image |
|-----------|-------|
| Konnectivity Server | `mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/server:v0.32.1-3` |
| Konnectivity Agent | `mcr.microsoft.com/oss/v2/kubernetes/apiserver-network-proxy/agent:v0.32.1-3` |
| VMAgent | `mcr.microsoft.com/oss/v2/victoriametrics/vmagent:v1.127.0-1` |
| VMSingle | `victoriametrics/victoria-metrics:v1.117.0` |

---

## What Gets Deployed

The test creates the following per tier (e.g., tier=150 creates 150 replicas × 4 roles = 600 targets):

### Control Plane Cluster (fakecpcluster)

| Resource | Namespace | Description |
|----------|-----------|-------------|
| Konnectivity Server (Deployment) | `loadtest-N` | 1 replica, LoadBalancer service, mTLS on :8083, agent gRPC on :8081, admin/pprof on :8096 |
| VMAgent (StatefulSet) | `loadtest-N` | 1 replica with vmagent-proxy sidecar (do_GET + do_CONNECT), 7 scrape jobs (4 real + 3 DaemonSet), pprof on :8429 |
| VMSingle (Deployment) | `loadtest-N` | 1 replica, receives remote writes on :8428, queryable via PromQL |
| konnectivity-certs (Secret) | `loadtest-N` | CA + server + client TLS certificates (generated by Python `cryptography` library) |
| kubelet-scrape-token (Secret) | `loadtest-N` | Bearer token for SD + kubelet auth (2h TTL) |

### Dataplane Cluster (fakedpcluster)

| Resource | Namespace | Description |
|----------|-----------|-------------|
| Konnectivity Agents (Deployment) | `loadtest-N` | N replicas, gRPC connection to server via LB IP, mTLS client certs, admin/pprof on :8094 |
| kubelet-scraper SA + CRBs | `loadtest-N` | ServiceAccount with `system:kubelet-api-admin` + `view` ClusterRoles |
| konnectivity-certs (Secret) | `loadtest-N` | CA + client TLS certificates |

---

## VMAgent Configuration

### Scrape Config (scrape-config.yaml)

The scrape configuration is stored in a **separate file** (`scrape-config.yaml`) from the VMAgent StatefulSet (`vmagent.yaml`). This makes it easy to add or modify scrape jobs without touching the deployment spec.

The scrape config is rendered as a ConfigMap (`vmagent-config`) with the `__DP_API_SERVER__` template variable replaced at deploy time.

### All Scrape Jobs

| # | Job Name | SD Role | Target | Port | Scheme | Mode |
|---|----------|---------|--------|------|--------|------|
| 1 | `real-kubelet` | node | nodeIP | 10250 | HTTPS | real |
| 2 | `real-cadvisor` | node | nodeIP | 10250 | HTTPS | real |
| 3 | `real-kubeproxy` | node | nodeIP | 10249 | HTTP | real |
| 4 | `real-azure-cns` | node | nodeIP | 10092 | HTTP | real |
| 5 | `localdns` | node | nodeIP | 9253 | HTTP | always |
| 6 | `node-problem-detector` | node | nodeIP | 20257 | HTTP | always |
| 7 | `csi-azuredisk-node` | pod | kube-system | named `metrics` | HTTP | always |

DaemonSet jobs (5-7) are always active but produce 0 targets if the service isn't running on the DP cluster.

### Dynamic Target Discovery (`kubernetes_sd_configs`)

All scrape jobs use `kubernetes_sd_configs` for automatic target discovery — **no hardcoded IPs or static configs**. VMAgent queries the DP cluster API server directly for node lists and relabels them into scrape targets.

#### Real-Targets Mode (role: node)

```yaml
scrape_configs:
  - job_name: real-kubelet
    stream_parse: true
    proxy_url: "http://localhost:8080"
    scheme: https
    metrics_path: /metrics
    authorization:
      type: Bearer
      credentials_file: /var/run/secrets/kubelet/token
    tls_config:
      insecure_skip_verify: true
    kubernetes_sd_configs:
      - role: node
        api_server: "https://<dp-api-server>"
        bearer_token_file: /var/run/secrets/kubelet/token
        tls_config:
          insecure_skip_verify: true
    relabel_configs:
      - source_labels: [__meta_kubernetes_node_address_InternalIP]
        target_label: __address__
        replacement: $1:10250
      - source_labels: [__address__]
        target_label: instance
```

Same pattern for `real-cadvisor` (/metrics/cadvisor :10250 HTTPS), `real-kubeproxy` (:10249 HTTP), `real-azure-cns` (:10092 HTTP).

#### DaemonSet Targets (role: node and pod)

```yaml
scrape_configs:
  # node-local-dns (role: node, port 9253)
  - job_name: localdns
    stream_parse: true
    proxy_url: "http://localhost:8080"
    kubernetes_sd_configs:
      - role: node
        api_server: "https://<dp-api-server>"
        bearer_token_file: /var/run/secrets/kubelet/token
        tls_config:
          insecure_skip_verify: true
    relabel_configs:
      - source_labels: [__meta_kubernetes_node_address_InternalIP]
        target_label: __address__
        replacement: $1:9253

  # NPD (role: node, port 20257)
  - job_name: node-problem-detector
    stream_parse: true
    proxy_url: "http://localhost:8080"
    kubernetes_sd_configs:
      - role: node
        ...
    relabel_configs:
      - source_labels: [__meta_kubernetes_node_address_InternalIP]
        target_label: __address__
        replacement: $1:20257
      - source_labels: [__meta_kubernetes_node_label_agentpool]
        target_label: nodepool

  # Azure Disk CSI node driver (role: pod, kube-system)
  - job_name: csi-azuredisk-node
    stream_parse: true
    proxy_url: "http://localhost:8080"
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names: ["kube-system"]
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        regex: csi-azuredisk-node.*
        action: keep
      - source_labels: [__meta_kubernetes_pod_container_name]
        regex: azuredisk
        action: keep
      - source_labels: [__meta_kubernetes_pod_container_port_name]
        regex: metrics
        action: keep
```

**Key differences between real-targets and DaemonSet jobs:**

| Aspect | Real Targets | DaemonSet Targets |
|--------|--------------|-------------------|
| SD role | `node` (all nodes) | `node` or `pod` (kube-system) |
| Proxy handler | `do_CONNECT` (HTTPS tunnel) | `do_GET` (HTTP) |
| TLS | `insecure_skip_verify: true` | None |
| Auth | Bearer token (2h TTL) | None (SD only uses token) |
| Scale | 3 nodes × 4 roles = 12 | 3 nodes × 2 + pods |
| Always active? | Only with `--real-targets` | Always |

**VMAgent flags (matching production):**

| Flag | Value | Purpose |
|------|-------|---------|
| `-promscrape.noStaleMarkers` | `true` | Don't send stale markers |
| `-promscrape.config.strictParse` | `true` | Strict config parsing |
| `-promscrape.maxScrapeSize` | `33554432` (32MB) | Max scrape response size |
| `-remoteWrite.url` | `http://vmsingle:8428/api/v1/write` | Remote write endpoint |
| `-remoteWrite.flushInterval` | `30s` | Flush interval |
| `-remoteWrite.sendTimeout` | `10s` | Send timeout |
| `-remoteWrite.maxDiskUsagePerURL` | `1073741824` (1GB) | WAL disk limit |
| `-remoteWrite.rateLimit` | `524288` (512KB/s) | Rate limit |
| `-remoteWrite.maxBlockSize` | `524288` (512KB) | Max block |
| `-remoteWrite.dropSamplesOnOverload` | `true` | Drop on overload |

---

## Running the Test

```bash
cd aks-operator

# Real targets — correctness validation (3 nodes × 4 roles = 12 targets)
python3 tests/scale/fake-controlplane/main.py \
  --cp-kubeconfig /tmp/fakecpcluster.kubeconfig \
  --dp-kubeconfig /tmp/fakedpcluster.kubeconfig \
  --tiers 3 \
  --warm-up-minutes 5 \
  --real-targets

# Real targets with DP node pool scaling (auto-scale DP to tier N nodes)
python3 tests/scale/fake-controlplane/main.py \
  --cp-kubeconfig /tmp/fakecpcluster.kubeconfig \
  --dp-kubeconfig /tmp/fakedpcluster.kubeconfig \
  --tiers 10,50,100 \
  --warm-up-minutes 10 \
  --real-targets \
  --resource-group VMAgent-Load-testing \
  --dp-cluster-name fakedpcluster

# Cleanup all loadtest namespaces
python3 tests/scale/fake-controlplane/main.py \
  --cp-kubeconfig /tmp/fakecpcluster.kubeconfig \
  --dp-kubeconfig /tmp/fakedpcluster.kubeconfig \
  --cleanup
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--cp-kubeconfig` | (required) | Control plane cluster kubeconfig |
| `--dp-kubeconfig` | (required) | Dataplane cluster kubeconfig |
| `--tiers` | `150,500,1000` | Comma-separated DP node counts per tier (targets = nodes × 4 real roles) |
| `--warm-up-minutes` | `5` | Max time to wait for targets to come up |
| `--real-targets` | `false` | Scrape real kubelet/cadvisor/kube-proxy/azure-cns endpoints on the DP cluster nodes |
| `--resource-group` | `""` | Azure resource group for DP cluster (enables node scaling) |
| `--dp-cluster-name` | `""` | AKS cluster name for DP (enables node scaling) |
| `--nodepool-name` | `nodepool1` | DP cluster nodepool to scale |
| `--cleanup` | `false` | Delete all loadtest namespaces and exit |
| `--verbose` / `-v` | `false` | Enable debug logging |

---

## Metrics Collected

### VMAgent Scrape Metrics

| Metric | Source | Description |
|--------|--------|-------------|
| `scrape_targets_up` | VMAgent `/api/v1/targets` | Number of targets with health=up |
| `scrape_targets_total` | VMAgent `/api/v1/targets` | Total discovered targets (via SD) |
| `scrape_success_rate` | Computed | `up / total` (threshold: >= 0.99) |
| `vmagent_scrape_duration_mean_seconds` | VMAgent `/metrics` | Mean scrape duration |
| `vmagent_scrapes_total` | `vm_promscrape_scrapes_total` | Total scrape attempts |
| `vmagent_scrapes_failed` | `vm_promscrape_scrapes_failed_total` | Failed scrapes |
| `vmagent_samples_scraped` | `vm_promscrape_scraped_samples_sum` | Total samples scraped |
| `vmagent_samples_post_relabeling` | `vm_promscrape_samples_post_relabeling_sum` | Samples after relabeling |

### VMAgent Network and Resource Metrics

| Metric | Source | Description |
|--------|--------|-------------|
| `vmagent_tcpdialer_dials_total` | `vm_tcpdialer_dials_total` | TCP dial attempts |
| `vmagent_tcpdialer_dial_mean_seconds` | `vm_tcpdialer_dial_duration_seconds` | Mean dial latency |
| `vmagent_resident_memory_bytes` | `process_resident_memory_bytes` | VMAgent RSS memory |
| `vmagent_goroutines` | `go_goroutines` | Active goroutines |
| `vmagent_cpu` | `kubectl top` | CPU usage |
| `vmagent_memory` | `kubectl top` | Memory usage |

### Konnectivity Server Metrics

| Metric | Source | Description |
|--------|--------|-------------|
| `konn_grpc_connections` | `konnectivity_network_proxy_server_grpc_connections` | Active gRPC connections from agents |
| `konn_ready_backend_connections` | `konnectivity_network_proxy_server_ready_backend_connections` | Ready backend agent connections |
| `konn_established_connections` | `konnectivity_network_proxy_server_established_connections` | Established tunnel connections |
| `konn_pending_dials` | `konnectivity_network_proxy_server_pending_dials` | Pending dial requests |
| `konn_dial_count` | `konnectivity_network_proxy_server_dial_duration_seconds_count` | Total dial count |
| `konn_dial_mean_seconds` | `konnectivity_network_proxy_server_dial_duration_seconds_sum / count` | Mean dial latency |
| `konn_stream_packets` | `konnectivity_network_proxy_server_stream_packets_total` | Total stream packets (by packet_type: DIAL_REQ, DIAL_RSP, DATA, CLOSE_REQ, CLOSE_RSP) |
| `konn_stream_errors` | `konnectivity_network_proxy_server_stream_errors_total` | Total stream errors |
| `konn_frontend_write_duration_mean` | `konnectivity_network_proxy_server_frontend_write_duration_seconds` | Mean frontend write latency |
| `konn_server_goroutines` | Server `:8096/metrics` | Active goroutines |
| `konn_server_cpu` | `kubectl top` | CPU usage |
| `konn_server_memory` | `kubectl top` | Memory usage |

### Konnectivity Agent Resources

| Metric | Source | Description |
|--------|--------|-------------|
| `konn_agent_resources` | `kubectl top` on DP | CPU/memory for each agent pod |
| `konnectivity_agent_cpu_rate` | PromQL from VMSingle (cadvisor) | Container CPU rate from cadvisor data |
| `konnectivity_agent_memory` | PromQL from VMSingle (cadvisor) | Container memory working set from cadvisor |

### Remote Write (VMSingle) Metrics

| Metric | Source | Description |
|--------|--------|-------------|
| `vmsingle_rows_inserted` | `vm_rows_inserted_total{type="promremotewrite"}` | Rows written |
| `vmsingle_http_requests_total` | `vm_http_requests_total{path="/api/v1/write"}` | Write requests received |
| `vmsingle_http_errors_total` | `vm_http_errors_total{path="/api/v1/write"}` | Write errors |
| `vmsingle_series_created` | `vm_new_timeseries_created_total` | New time series |
| `vmsingle_series_up_count` | PromQL `count(up)` | Queryable UP series |

### Pod Health Metrics

| Metric | Source | Description |
|--------|--------|-------------|
| `oom_events` | `kubectl get events --field-selector reason=OOMKilled` | OOM kill events (both clusters) |
| `pod_restarts_total` | `pod.status.containerStatuses[].restartCount` | Total container restarts (both clusters) |
| `pod_oom_killed` | `pod.status.containerStatuses[].lastState.terminated.reason` | Pods terminated with OOMKilled |
| `pod_restart_details` | Per-component breakdown | Name, restart count, last termination reason for each pod |

### Resource Time Series Sampling

During the warm-up phase, the test **samples resource usage every polling cycle** (every ~5-8s):

| Component | Cluster | Label | Metrics |
|-----------|---------|-------|---------|
| vmagent | CP | `app=vmagent` | CPU, memory per pod |
| konnectivity-server | CP | `app=konnectivity-server` | CPU, memory per pod |
| konnectivity-agent | DP | `app=konnectivity-agent` | CPU, memory per pod (all replicas) |

These samples are stored in the results JSON as `resource_samples[]` with timestamps and `targets_up` count, enabling resource-vs-target-count correlation analysis.

---

## pprof Profiling

The test automatically collects **Go pprof profiles** from all three key components after metrics collection:

| Component | Cluster | Port | Enabled By |
|-----------|---------|------|-----------|
| Konnectivity Server | CP | :8096 (admin) | `--enable-profiling` + `--admin-port=8096` |
| Konnectivity Agent | DP | :8094 (admin) | `--enable-profiling` + `--admin-bind-address=0.0.0.0` + `--admin-server-port=8094` |
| VMAgent | CP | :8429 (HTTP) | Built-in (Go standard `net/http/pprof`) |

### Profile Types Collected

| Profile | Endpoint | Duration | Description |
|---------|----------|----------|-------------|
| heap | `/debug/pprof/heap` | instant | In-use memory allocation |
| allocs | `/debug/pprof/allocs` | instant | All past memory allocations |
| goroutine | `/debug/pprof/goroutine` | instant | Current goroutine stacks |
| cpu | `/debug/pprof/profile?seconds=30` | 30s | CPU profile (sampling) |

### Auto-Analysis

After collecting profiles, the test runs `go tool pprof -top` on each `.pb.gz` file and produces:

- **Structured JSON** with top 15 functions (flat, flat%, sum%, cum, cum%, function name) per profile
- **Summary indicators**: `goroutine_count`, `heap_total` extracted per component
- **Raw `.top.txt` files** saved alongside `.pb.gz` for manual inspection

### Sample pprof Output (Tier 3 — 12 real targets)

| Component | Heap | Goroutines | CPU (30s) | Allocs |
|-----------|------|-----------|-----------|--------|
| konn-server | 5.2 kB | 41 | 60ms | 16.0 kB |
| konn-agent | 4.2 kB | 23 | 20ms | 6.8 kB |
| vmagent | 11.7 kB | 92 | 60ms | 112 MB |

These values become significant at higher tiers (500+ nodes) where memory and goroutine growth patterns reveal bottlenecks.

### Results JSON Structure

```json
{
  "pprof": {
    "konn_server": {
      "files": {"heap": "/path/konn-server-heap-tier3.pb.gz", ...},
      "analysis": {
        "heap": {"header": "Type: inuse_space", "total": "Showing nodes...", "top_functions": [...]},
        "goroutine": {...},
        "cpu": {...},
        "allocs": {...},
        "goroutine_count": 41,
        "heap_total": "Showing nodes accounting for 5200.80kB, 100% of 5200.80kB total"
      }
    },
    "konn_agent": { ... },
    "vmagent": { ... }
  }
}
```

---

## Pass/Fail Criteria

| Criterion | Threshold | Description |
|-----------|-----------|-------------|
| Scrape success rate | >= 99% | All targets must be scrapeable through tunnel |
| OOM events | = 0 | No components should OOM (events + terminated pods) |
| Pod restarts | = 0 | No containers should restart |
| Konnectivity dial mean latency | < 2.0s | Tunnel setup must be fast |
| Remote write errors | = 0 | No write failures to VMSingle |
| Remote write rows inserted | > 0 | Data must actually arrive at receiver |

**Overall: PASS only if ALL criteria pass.**

---

## Sample Results

### Real Targets — Correctness Validation (3 nodes, 12 targets)

Test **PASSED**: 3 DP nodes × 4 real endpoints (kubelet, cadvisor, kube-proxy, azure-cns) = 12 targets, all scraped end-to-end through the konnectivity tunnel.

#### Scrape & Success

| Metric | Real (3 nodes, 12 targets) | Status |
|--------|-----------------------------|--------|
| Scrape targets UP | 12/12 | :white_check_mark: |
| Scrape success rate | 100% | :white_check_mark: |

#### Konnectivity Tunnel

| Metric | Real (3 nodes) | Status |
|--------|-----------------|--------|
| Konn dial mean | 2.1ms | :white_check_mark: |
| Konn gRPC connections | 3 | :white_check_mark: |
| Konn ready backends | 3 | :white_check_mark: |
| Konn established connections | 6 | info |
| Konn total dials | 21 | info |
| Konn stream packets | 622 | info |
| Konn stream errors | 54 | info |
| Konn pending dials | 0 | :white_check_mark: |
| Connections/sec | ~0.4 (12/30) | matches formula |

#### Remote Write & Data Validation

| Metric | Real (3 nodes) | Status |
|--------|-----------------|--------|
| Remote write rows | 30,000 | :white_check_mark: |
| Remote write errors | 0 | :white_check_mark: |
| VMSingle UP series | 12 | :white_check_mark: |

#### Health & Resources

| Metric | Real (3 nodes) | Status |
|--------|-----------------|--------|
| Pod restarts | 0 | :white_check_mark: |
| OOM events | 0 | :white_check_mark: |

#### pprof Profiles

| Component | Real (3 nodes) |
|-----------|-----------------|
| konn-server heap | 5.2 kB, 41 goroutines |
| konn-agent heap | 4.2 kB, 23 goroutines |
| vmagent heap | 11.7 kB, 92 goroutines |

#### Overall

| | Real (3 nodes, 12 targets) |
|--|----------------------------|
| **Result** | **PASS** :white_check_mark: |

**Key takeaway:** Real kubelet (~2,300 series), cadvisor (~37,700 series), kube-proxy (~500 series), and azure-cns (~200 series) all scraped successfully through the konnectivity HTTPS CONNECT tunnel. The `do_CONNECT` proxy handler passes TLS and bearer token auth end-to-end, confirming the pipeline works with production-grade metrics.

---

## File Structure

```
tests/scale/fake-controlplane/
├── main.py                                       # Entry point: argparse + main() orchestration
├── modules/
│   ├── config/
│   │   └── manifest/
│   │       ├── konnectivity-agent.yaml           # Agent deployment (--enable-profiling, admin :8094)
│   │       ├── konnectivity-server.yaml          # Server deployment + LB service (--enable-profiling, admin :8096)
│   │       ├── scrape-config.yaml                # VMAgent scrape config ConfigMap (11 jobs, separated from vmagent.yaml)
│   │       ├── vmagent.yaml                      # VMAgent StatefulSet + proxy sidecar (references scrape-config.yaml ConfigMap)
│   │       └── vmsingle.yaml                     # VMSingle receiver deployment + service
│   └── python/
│       └── vmagent_loadtesting/                  # Python package
│           ├── __init__.py
│           ├── certs.py                          # Pure-Python TLS cert generation (cryptography library, no cfssl)
│           ├── config.py                         # Constants: images, roles, ports, paths
│           ├── deploy.py                         # K8s deployment helpers (ensure_namespace, deploy_*, setup_dp_access, get_dp_api_server)
│           ├── metrics.py                        # Metrics collection, pprof profiling + auto-analysis, pass/fail evaluation
│           ├── runner.py                         # Single-tier execution (run_single_tier) + cleanup
│           ├── scaling.py                        # Azure DP nodepool scaling (az aks nodepool scale)
│           └── utils.py                          # kubectl wrapper, template rendering, PortForward context manager, retry_request
├── pipeline/
│   └── fake-cp-loadtest.yaml                     # Azure Pipelines (3 stages: create clusters → run test → cleanup)
└── __pycache__/
```

### Key Module Responsibilities

| Module | Lines | Responsibility |
|--------|-------|---------------|
| `main.py` | ~125 | CLI parsing, tier loop, results summary |
| `config.py` | ~50 | Image tags, real/DaemonSet role definitions, logging |
| `deploy.py` | ~220 | All `kubectl apply` operations, namespace management, RBAC, token transfer |
| `metrics.py` | ~600 | Prometheus metric extraction, pprof collection (3 components) + auto-analysis, resource sampling, pass/fail |
| `runner.py` | ~155 | Single-tier orchestration: deploy → wait → collect → evaluate → write JSON |
| `certs.py` | ~80 | CA + server + client cert generation using Python `cryptography` library |
| `utils.py` | ~95 | `kubectl()` subprocess wrapper, YAML template rendering, `PortForward` context manager |
| `scaling.py` | ~40 | `az aks nodepool scale` + `wait_for_nodes_ready` |

---

## CI/CD Pipeline

The Azure Pipelines definition (`pipeline/fake-cp-loadtest.yaml`) automates the full flow:

| Stage | Description | Timeout |
|-------|-------------|---------|
| **Setup** | Creates resource group + CP/DP AKS clusters, publishes kubeconfigs | 30 min |
| **LoadTest** | Runs `main.py` with configured tiers, publishes results JSON | 180 min |
| **Cleanup** | Deletes resource group (conditional on `deleteAfterTest`) | 15 min |

### Pipeline Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `scaleTiers` | `150,500,1000,2000` | DP node counts per tier |
| `soakMinutes` | `10` | Soak duration per tier |
| `cpNodeCount` | `3` | CP cluster node count |
| `dpNodeCount` | `10` | DP cluster node count |
| `location` | `westus2` | Azure region |
| `vmSize` | `Standard_D4s_v3` | VM size for both clusters |
| `deleteAfterTest` | `true` | Delete clusters after test |

---

## Cleanup

```bash
# Delete loadtest namespaces on both clusters
python3 tests/scale/fake-controlplane/main.py \
  --cp-kubeconfig /tmp/fakecpcluster.kubeconfig \
  --dp-kubeconfig /tmp/fakedpcluster.kubeconfig \
  --cleanup

# Also clean up real-targets RBAC if needed
kubectl --kubeconfig /tmp/fakedpcluster.kubeconfig delete clusterrolebinding kubelet-scraper-kubelet
kubectl --kubeconfig /tmp/fakedpcluster.kubeconfig delete clusterrolebinding kubelet-scraper-view

# Delete the entire resource group (deletes both AKS clusters)
az group delete --name VMAgent-Load-testing --no-wait --yes
```

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-30 | Removed fake-exporter/fake-node references from this page (Mode 1, diagrams, tables, Sample Results); page now documents real-target (`--real-targets`) validation exclusively |
| 2026-07-30 | Synced `-remoteWrite` flags to current prod (`flushInterval` 30s→1s, `rateLimit` .5→2 MiB/s, added `label=cluster_id`/`showURL`); added new `--max-block-size` (→8 MiB) / `--max-rows-per-block` (new flag) CLI args to validate prod's pending/unvalidated 2k-node-incident recommendations (see `aks-operator/config/channels/packages/adx-vmagent/vmagent-loadtest-analysis.md`) |
| 2026-07-30 | Aligned `konnectivity-server.yaml` with the real standalone `konnectivity-server-synth` chart (post apiserver/konnectivity split): admin/metrics port 8095→8096, added `--graceful-shutdown-timeout=15s` and `--cipher-suites` restriction |
| 2026-04-21 | Added DaemonSet scrape targets: localdns (:9253), node-problem-detector (:20257), csi-azuredisk-node (kube-system) matching production KCL configs |
| 2026-04-21 | Separated scrape config into `scrape-config.yaml` (11 jobs total); `vmagent.yaml` now only contains StatefulSet + proxy sidecar |
| 2026-04-21 | Added "Why VMSingle Instead of vmagent-metric-receiver" section explaining PromQL query requirements |
| 2026-04-21 | Reformatted Sample Results: fake vs real targets shown side by side for easier comparison |
| 2026-04-20 | Full wiki rewrite: updated all sections to reflect current codebase |
| 2026-04-17 | Added pprof profiling for all 3 components (konn-server, konn-agent, vmagent) with auto-analysis via `go tool pprof -top` |
| 2026-04-17 | Replaced `static_configs` with `kubernetes_sd_configs` for dynamic target discovery |
| 2026-04-17 | Added azure-cns as 4th real target role (port 10092) — real targets now 3 × 4 = 12 |
| 2026-04-17 | Enhanced metrics: resource time series sampling during warm-up, pod restart/OOM tracking, cadvisor container queries from VMSingle |
| 2026-04-17 | Enabled `--enable-profiling` on konnectivity-agent with admin port 8094 |
| 2026-04-15 | Restructured from monolithic script to modular Python package (`modules/python/vmagent_loadtesting/`) |
| 2026-04-15 | Replaced cfssl cert generation with pure Python `cryptography` library |
| 2026-04-14 | Added `--real-targets` mode with `do_CONNECT` proxy handler for HTTPS targets |
| 2026-04-13 | Initial implementation with fake exporter targets and static configs |
