[[_TOC_]]

# VMAgent Node-Aggregator Prototype vs Direct Scrape — Comparison Report

_Data-driven comparison of the node-aggregator prototype — a real Prometheus running as a DaemonSet
on every node, federated by central vmagent — against today's direct-scrape design, where central
vmagent dials each of 6 real-target roles plus 2 CSI roles individually per node through
konnectivity. Based on a real A/B load test (ADO pipeline build
[80259](https://dev.azure.com/akstelescope/telescope/_build/results?buildId=80259)) run against the
same 500-2,000 node cluster for both combos, with results ingested into ADX for analysis.
Last updated 2026-09-22 — see "Round 3 validation" note under Recommendations for a follow-up run
that confirms the node-aggregator-side fixes below without new baseline data._

## TL;DR

- Aggregator cuts central remote-write row volume by **~42-51%** and konn-server memory/CPU by
  **~70%**, with identical dial latency and zero dial errors (vs real errors seen in baseline).
- It adds a new, **permanent per-node cost** (~120-150MB memory, ~0.007-0.013 cores) since the
  DaemonSet has no node selector — it runs on every DP node whether or not that node is currently
  in the central scrape scope. At fleet scale this is the real trade-off to weigh.
- The configured memory **request (64Mi) is undersized** relative to observed usage — bump before
  any real deployment.
- One metric (vmagent's own peak memory) is genuinely inconclusive — no consistent direction,
  likely affected by the harness's cumulative-max measurement method, not a real regression signal.
- Comparison is apples-to-apples: identical node counts and konn-server/konn-agent/vmagent replica
  counts confirmed at every tier.

## Architecture recap

- **Baseline (today's prod design)**: central vmagent dials 6 real-target roles (kubelet, cadvisor,
  kube-proxy, azure-cns, node-exporter, node-runtime) + 2 CSI DaemonSet roles (csi-azuredisk-node,
  csi-azurefile-node) **individually, per node**, through the konnectivity tunnel — 8 scrape
  round-trips per node.
- **Aggregator prototype**: a real, unmodified Prometheus runs as a DaemonSet on every DP node
  (`manifests/node-aggregator.yaml`), scrapes all 8 roles **locally** via `localhost` (hostNetwork),
  and exposes one combined `/federate` endpoint. Central vmagent scrapes **one** target per node
  through the tunnel instead of 8.

## Test methodology

- Harness: `run_real_targets_ramp(..., fixed_pools=True)`, `TIERS=500,1000,1500,2000`,
  `MEASURE_DRAIN=true` (180s), matching the real pipeline's `real_targets_sweep` matrix leg.
  Both combos ran sequentially against the **same** provisioned CP/DP clusters — no
  cluster-to-cluster variance.
- konn-server metrics are sampled from **one arbitrary replica** (port-forward to
  `deployment/konnectivity-server` picks one pod out of the fleet) — absolute values are per-replica
  snapshots, not fleet sums. Both combos are sampled identically, so the *comparison* is still fair.

## Results

### Apples-to-apples sizing (identical at every tier)

| Tier | DpNodeCount | KonnServerReplicas | KonnAgentReplicas | VmagentReplicas |
|---|---:|---:|---:|---:|
| 500 | 500 = 500 | 4 = 4 | 6 = 6 | 2 = 2 |
| 1000 | 1000 = 1000 | 7 = 7 | 6 = 6 | 3 = 3 |
| 1500 | 1500 = 1500 | 10 = 10 | 6 = 6 | 4 = 4 |
| 2000 | 2000 = 2000 | 13 = 13 | 6 = 6 | 5 = 5 |

### Remote-write volume (the headline win)

| Tier | Baseline rows | Aggregator rows | Reduction |
|---|---:|---:|---:|
| 500 | 3,434,505 | 2,006,773 | **-41.6%** |
| 1000 | 11,528,727 | 5,650,956 | **-51.0%** |
| 1500 | 20,936,154 | 11,861,451 | **-43.3%** |
| 2000 | 33,142,856 | 17,340,784 | **-47.7%** |

### konn-server cost (per sampled replica)

| Tier | Metric | Baseline | Aggregator |
|---|---|---:|---:|
| 500 | Memory peak | 204 MB | 59 MB |
| | CPU peak | 0.31 cores | 0.06 cores |
| 1000 | Memory peak | 210 MB | 59 MB |
| | CPU peak | 0.12 cores | 0.06 cores |
| 1500 | Memory peak | 210 MB | 59 MB |
| | CPU peak | 0.32 cores | 0.07 cores |
| 2000 | Memory peak | 210 MB | 59 MB |
| | CPU peak | 0.13 cores | 0.0 cores |

~**71% lower memory**, roughly half-to-a-fifth the CPU, consistently at every tier.

### konn-server / konn-agent connections (single-replica sample; both modes sampled identically)

| Tier | Metric | Baseline | Aggregator |
|---|---|---:|---:|
| 500 | established_connections | 1,767 | 120 |
| | dial_count | 1,867 | 120 |
| | stream_errors_total | 58 | 55 |
| | agent open_endpoint_connections | 3,325 | 77 |
| 1000 | established_connections | 1,412 | 143 |
| | dial_count | 1,446 | 143 |
| | stream_errors_total | 24 | 8 |
| | agent open_endpoint_connections | 232 | 9 |
| 1500 | established_connections | 1,303 | 157 |
| | dial_count | 1,746 | 184 |
| | stream_errors_total | 31 | 3 |
| | agent open_endpoint_connections | 240 | 0 |
| 2000 | established_connections | 1,237 | 135 |
| | dial_count | 2,167 | 166 |
| | stream_errors_total | 22 | 5 |
| | agent open_endpoint_connections | 1,853 | 0 |

Dial latency (mean/p50/p90) is essentially identical between modes at every tier (~0.0035-0.0041s
mean, 0.005s p50, 0.025s p90) — the aggregator changes connection *volume*, not per-dial performance.

### vmagent-proxy (client-side view — newly instrumented in this run)

| Tier | Metric | Baseline | Aggregator |
|---|---|---:|---:|
| 500 | active_connections | 3,014 | 267 |
| | dials (ok/error) | 3,415 / **55** | 267 / **0** |
| | dial_mean_seconds | **4.91s** | 0.015s |
| 1000 | active_connections | 2,696 | 343 |
| | dials (ok/error) | 2,696 / 0 | 343 / 0 |
| | dial_mean_seconds | **2.59s** | 0.024s |
| 1500 | active_connections | 2,495 | 353 |
| | dial_mean_seconds | **2.59s** | 0.018s |
| 2000 | active_connections | 2,509 | 403 |
| | dials (ok/error) | 3,004 / **187** | 403 / **0** |
| | dial_mean_seconds | **5.45s** | 0.020s |

Baseline shows real dial errors at 2 of 4 tiers (55, 187) and dial means in the multi-second range;
aggregator shows **zero dial errors at every tier** and consistently sub-30ms dial means. This is a
genuinely interesting new signal — worth a repeat run before treating it as a stable characteristic
rather than a one-off contention artifact, but directionally favorable to the aggregator. A 3rd run
(build 80885, aggregator combo only) again showed zero dial errors and 15-25ms mean dial times at
all 4 tiers — consistent with this table, though still without a fresh baseline-side data point.

### node-aggregator's own cost (this is the new line item)

| Tier | Memory peak | CPU peak |
|---:|---:|---:|
| 500 | 121.5 MB | 0.0087 cores |
| 1000 | 137.0 MB | 0.0123 cores |
| 1500 | 137.0 MB | 0.0078 cores |
| 2000 | 148.3 MB | 0.0076 cores |

Cross-validated by direct pod sampling (bypassing the metrics pipeline entirely): ~108-138MB /
~0.0023-0.0075 cores per pod, consistent with the ADX-ingested numbers above. A 3rd independent
run (build 80885, node-aggregator combo only — see Recommendations) landed in the same range again:
113.5 / 120.0 / 119.0 / 125.9 MB across the 4 tiers, comfortably inside the 176Mi memory request.

### Inconclusive: vmagent's own peak memory

| Tier | Baseline | Aggregator |
|---|---:|---:|
| 500 | 370 MB | 194 MB |
| 1000 | 589 MB | 496 MB |
| 1500 | 428 MB | 527 MB |
| 2000 | 428 MB | 527 MB |

No consistent direction. `adx.py` computes this as a **cumulative max since ramp start**, so a peak
reached at an earlier tier gets carried into later tiers' rows — this column isn't reliable for a
per-tier comparison as currently measured. A plausible (unconfirmed) mechanism for aggregator mode
running higher at some tiers: each `/federate` scrape returns one large batched payload
(~7,000-8,000 samples) vmagent must parse/buffer per scrape, vs baseline's many smaller per-role
responses — needs a dedicated windowed measurement to confirm before drawing a conclusion.

**Update (build 80885)**: the windowed-per-tier fix (see Recommendations) shows a new problem
instead of resolving this one — the aggregator combo returned valid values at tiers 500/1000
(190 MB / 519 MB) but **0 MB at tiers 1500/2000**, both tiers where the CP nodepool scale-up plus
vmagent StatefulSet reconcile ate several minutes of the tier's own (now much shorter) window,
leaving too little vmagent-self uptime inside it for the query to find a sample. The fix trades
cumulative-max inflation for occasional false zeros at tiers with a slow reconcile — needs a
minimum-window floor or a wait for vmagent's own rollout to complete before starting the window.

## Fleet-wide cost impact: adding node-aggregator as a DaemonSet on customer/overlay nodes

This is the key operational question: **node-aggregator has no node selector**, so if shipped, it
would run on **every** DP/customer node, permanently, regardless of whether that specific node's
data is currently wanted by the central scrape scope (tier-block or otherwise). The per-node cost
observed here (~120-150MB memory, ~0.008-0.012 cores) is not conditional — it's a fleet-wide tax.

| Fleet size (nodes) | Total memory (@ ~140MB/pod) | Total CPU (@ ~0.01 cores/pod) |
|---:|---:|---:|
| 500 | ~70 GB | ~5 cores |
| 2,000 | ~280 GB | ~20 cores |
| 10,000 | ~1.4 TB | ~100 cores |
| 50,000 | ~7 TB | ~500 cores |

Per-node the cost is negligible relative to any real VM's capacity (a few hundred MB / <1% of a
core), but it is a **new, permanent resident cost on every customer node in the fleet**, not just
the nodes actively being scraped — this is fundamentally different from vmagent/konn-server's
current footprint, which lives centrally and doesn't scale 1:1 with customer node count in the same
way. Sizing conversations should treat this as "cost per node, fleet-wide," not "cost per
monitored target."

## Pros

1. **~42-51% fewer remote-write rows** ingested centrally at every tier tested — lower central
   vmagent/storage cost, lower egress volume through the konnectivity tunnel.
2. **~71% lower konn-server memory**, roughly 2-5x lower CPU — smaller/fewer konn-server replicas
   may be sufficient at the same node count.
3. **8-17x fewer established tunnel connections** at every tier — less connection churn, less
   proxy-dial pressure on both konn-server and konn-agent.
4. **Zero vmagent-proxy dial errors** across all 4 tiers in this run (vs real errors at 2/4 tiers in
   baseline), with consistently low (<30ms) dial latency vs baseline's multi-second dial means.
5. True 1-scrape-per-node design achieved after folding CSI jobs into the DaemonSet's local scrape —
   central vmagent's per-node target count drops from 8 to 1.
6. Shard-count formula now matches prod's real `NodeToVMPodRatio=450` exactly, so these results
   reflect realistic fleet replica sizing, not an approximation.

## Cons / risks

1. **Per-node cost was previously unconditional of scrape scope** — the DaemonSet ran on every DP
   node, fleet-wide, regardless of whether that node was in central vmagent's current scrape scope
   (see table above for the per-node/fleet-wide cost estimate). **Fixed and validated (build
   80885)**: node-aggregator now takes the same tier-block node affinity as vmagent's own
   scrape-config regex — pipeline logs confirm it redeployed with `tier_block_regex=a`, then `a|b`,
   `a|b|c`, `a|b|c|d` in lockstep with each tier step, instead of running on all 2000 nodes from the
   start.
2. **Configured memory request (64Mi) was undersized** relative to observed usage (~1.6-2.2x over).
   **Fixed and validated (build 80885)**: raised to 176Mi; observed usage (113.5-125.9 MB) stayed
   comfortably under it across all 4 tiers.
3. **vmagent's own peak memory is inconclusive** — the measurement was a cumulative max since ramp
   start, carrying an earlier tier's peak into later tiers' rows. **Partially fixed**: now windowed
   to each tier's own step instead of the whole ramp, but build 80885 exposed a new gap — the
   narrower window can return 0 (no data) at tiers where the reconcile itself eats most of the
   window (see "Inconclusive" section above). Still not usable for a real verdict.
4. **Operational/maintenance burden**: a new component whose scrape/relabel/keep-filter config must
   be kept in lock-step with the central config's own filters — a drift risk every time the central
   scrape config changes (e.g. cadvisor's curated metric list) that doesn't exist today.
5. **hostNetwork: true requirement** on every node — a policy/security consideration for locked-down
   or customer-restricted clusters that don't already run this way.
6. Local `/federate` port (9090) in this prototype is reachable via `localhost` only in this test
   setup; a real deployment needs an explicit security review of that port's exposure/authn before
   shipping to customer nodes (not evaluated in this test).

## Recommendations / open questions

- ~~Raise node-aggregator's memory **request** from 64Mi to ~160-192Mi to reflect observed usage.~~
  Done and validated — bumped to 176Mi, observed usage stayed well under it in build 80885.
- ~~Decide whether node-aggregator should ship with a node selector (only deploy where the central
  scrape scope actually needs it).~~ Done and validated — it now takes the same tier-block node
  affinity vmagent's scrape config uses; build 80885's logs confirm it grows in lockstep with each
  tier instead of running unconditionally on every node.
- Investigate the vmagent peak-memory measurement further — the per-tier windowing fix traded
  cumulative-max inflation for occasional 0/no-data results at tiers where the CP scale-up +
  vmagent reconcile eats most of the window (seen at tiers 1500/2000 in build 80885). Needs either
  a minimum window floor or to start the window from when vmagent's own rollout completes, not
  from the tier step's start.
- Re-run the full A/B ramp (baseline + aggregator) to get a fresh baseline-side comparison — build
  80885's baseline combo failed 3/3 attempts on `kubectl rollout status
  deployment/konnectivity-agent-autoscaler --timeout=300s` before even reaching tier 500. This
  looks like a flake in the `imranpochi/kas-dev:multiple-ns` dev autoscaler image (already a known
  fragility on this branch, see repo memory), unrelated to any node-aggregator code change — it
  never got far enough to touch node-aggregator at all. Only the aggregator combo produced data
  this round (used for the validations above); no new reduction-% or konn-server comparison numbers
  from build 80885.
- Security review of the local federate/self-scrape port before considering this for real customer
  overlay nodes — still open, not something a load test can validate on its own.

### Round 3 validation (build 80885, 2026-09-22)

Ran to confirm the 3 fixes above. The baseline combo failed before producing any data (see bullet
above); the aggregator combo completed all 4 tiers (final tier: 100% scrape coverage, `success`).
Confirmed working as designed: node-aggregator's node affinity tracked the tier-block regex exactly
(`a` → `a|b` → `a|b|c` → `a|b|c|d`), and its memory/CPU cost (113.5-125.9 MB, ~0-0.0014 cores) plus
vmagent-proxy's zero-dial-errors/15-25ms-latency signal both landed in the same range as builds
80259/80574 — a 3rd consistent data point for those two findings. VmagentMemMaxBytes surfaced the
new windowing gap noted above. No baseline comparison data this round.

## Data sources

- ADO pipeline build [80259](https://dev.azure.com/akstelescope/telescope/_build/results?buildId=80259)
  (branch `sumanth/vmagent-node-aggregator-prototype` @ `efaa7fdbdb27525ee0f9c86552a5954fcc613ae1`),
  run IDs `20260915-183902` (baseline) / `20260915-191453` (aggregator).
- ADO pipeline build [80574](https://dev.azure.com/akstelescope/telescope/_build/results?buildId=80574)
  (same branch/commit, re-run on 2026-09-18 to check reproducibility), run IDs
  `20260918-160443` (baseline) / `20260918-170031` (aggregator).
- ADO pipeline build [80885](https://dev.azure.com/akstelescope/telescope/_build/results?buildId=80885)
  (same branch, commit `49ce3406f` — includes the 3 fixes above), run 2026-09-22. Aggregator-only
  data, run ID `20260921-224222`; baseline combo failed before producing a run ID (see
  Recommendations).
- ADX: `vmagent-loadtesting.eastus2.kusto.windows.net` / `vmagentloadtest`, table `VMAgentRunSummary`,
  filtered to the `RunId`s above, all rows with `DpNodeCount > 0`.
- Local validation: single-tier (500-node) smoke runs and direct pod-level sampling of
  `node-aggregator` and `vmagent-proxy` `/metrics` endpoints, used to cross-validate the ADX numbers.
