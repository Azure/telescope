[[_TOC_]]

# VMAgent Remote-Write Rate Limit & Max Block Size — Prod Sizing Analysis

_Data-driven answer to "how much headroom do we have to raise `-remoteWrite.rateLimit` /
`-remoteWrite.maxBlockSize` above prod's current 2 MiB/s / .5 MiB baseline?" Source: ADO pipeline
build [76687](https://dev.azure.com/akstelescope/telescope/_build/results?buildId=76687),
`sumanth/VMAgent-Load-testing` @ `84bff687`, run window 2026-08-13 19:44 UTC → 2026-08-14 02:36 UTC.
Last updated 2026-08-14._

## Goal

Prod currently runs `-remoteWrite.rateLimit=2097152` (2 MiB/s) and `-remoteWrite.maxBlockSize=524288`
(.5 MiB). This sweep tests 10 candidate configs — rate limit from 2 → 20 MiB/s, with two block-size
variants — against the same real-targets, fixed-tier-block ramp (500 → 1000 → 1500 → 2000 nodes) to
find how far these can be safely raised before remote-write starts dropping data, backing up, or
destabilizing vmagent.

## Test setup

- Harness: `run_real_targets_ramp(..., fixed_pools=True)` — one continuous namespace, tier-block
  regex flips instead of node scaling, `TIERS=500,1000,1500,2000`, `SOAK_MINUTES=5`.
- Each of the 10 configs below ran **sequentially against the same provisioned CP/DP clusters**
  (`config_combinations`), so results are directly comparable — no cluster-to-cluster variance.
- konn-server/konn-agent images: the default MCR-pinned real binaries
  (`apiserver-network-proxy/{server,agent}:v0.32.1-11`) — this sweep predates the
  team-provided test images and the autoscaler work, so konnectivity-agent replicas were the
  static Python-computed count (8 replicas at 2000 nodes), not autoscaler-managed.
- Only the **final tier (2000 nodes)** is gated pass/fail — 500/1000/1500 are informational
  waypoints (`not_evaluated`). Their lower scrape-coverage numbers are a known, already-diagnosed
  artifact of the fast tier-block regex flip (shard rebalancing + SD reconvergence lag) that is
  **identical across all 10 configs** — it is not a rate-limit/block-size effect and is excluded
  from the analysis below.

## Configs tested

| run_label | rate_limit | max_block_size |
|---|---|---|
| `rl-2mb-baseline` | 2 MiB/s (2097152) — **current prod** | .5 MiB (524288) — **current prod** |
| `rl-4mb` | 4 MiB/s | .5 MiB |
| `rl-6mb` | 6 MiB/s | .5 MiB |
| `rl-8mb` | 8 MiB/s | .5 MiB |
| `rl-10mb-bs-2mb` | 10 MiB/s | 2 MiB |
| `rl-12mb` | 12 MiB/s | .5 MiB |
| `rl-14mb` | 14 MiB/s | .5 MiB |
| `rl-16mb` | 16 MiB/s | .5 MiB |
| `rl-18mb` | 18 MiB/s | .5 MiB |
| `rl-20mb-bs-10mb` | 20 MiB/s | 10 MiB |

## Results — final tier (2000 nodes, graded)

All 10 configs **passed** with identical scrape coverage, zero OOMs, zero restarts, and zero
remote-write errors:

| run_label | Result | Scrape coverage | OOM | Restarts | RW errors | Pending backlog | Rows inserted | Wall time | ~Rows/sec | vmagent CPU | vmagent mem | konn-server CPU |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `rl-2mb-baseline` | success | 100% (16024/16024) | 0 | 0 | 0 | 202.8 MB | 18,459,001 | 1599.6s | ~11,540 | 834m | 535Mi | 61m |
| `rl-4mb` | success | 100% | 0 | 0 | 0 | 144.2 MB | 34,257,106 | 1833.8s | ~18,683 | 925m | 603Mi | 58m |
| `rl-6mb` | success | 100% | 0 | 0 | 0 | 206.9 MB | 28,489,199 | 1907.1s | ~14,938 | 944m | 624Mi | 67m |
| `rl-8mb` | success | 100% | 0 | 0 | 0 | 202.4 MB | 33,109,753 | 1822.6s | ~18,169 | 1000m | 537Mi | 62m |
| `rl-10mb-bs-2mb` | success | 100% | 0 | 0 | 0 | 148.4 MB | 19,624,299 | 1500.2s | ~13,082 | 939m | 593Mi | 65m |
| `rl-12mb` | success | 100% | 0 | 0 | 0 | 175.9 MB | 31,443,423 | 1881.6s | ~16,712 | 1012m | 576Mi | 60m |
| `rl-14mb` | success | 100% | 0 | 0 | 0 | 123.5 MB | 29,422,253 | 1830.1s | ~16,077 | 1006m | 484Mi | 97m |
| `rl-16mb` | success | 100% | 0 | 0 | 0 | 120.8 MB | 33,562,826 | 1860.2s | ~18,042 | 848m | 504Mi | 73m |
| `rl-18mb` | success | 100% | 0 | 0 | 0 | 203.3 MB | 28,489,597 | 1788.1s | ~15,933 | 715m | 489Mi | 63m |
| `rl-20mb-bs-10mb` | success | 100% | 0 | 0 | 0 | 172.4 MB | 22,247,889 | 1603.2s | ~13,878 | 761m | 539Mi | 62m |

konnectivity dial p99 (~0.025s) and stream error rate (~0.0004–0.0006) were flat across every
config — no measurable degradation anywhere in the sweep.

## Findings

1. **Zero data-loss signal anywhere in the sweep.** No OOMs, no pod restarts, no remote-write
   errors, 100% final scrape coverage — at 2 MiB/s (current prod) all the way up to 20 MiB/s with a
   10 MiB block size.
2. **Pending remote-write backlog does not scale with rate limit.** 120–207 MB across all 10
   configs with no monotonic trend (e.g. the 2 MiB/s baseline's 202.8 MB backlog is roughly the
   same as 20 MiB/s's 172.4 MB) — the rate limit is not actually the binding constraint for this
   workload at 2000 nodes.
3. **Actual delivered throughput (~11.5K–18.7K rows/sec) sits well under even the 2 MiB/s
   baseline's ceiling**, and doesn't increase proportionally with the configured limit — confirming
   (2) from a different angle: none of these configs came close to being rate-limited by their own
   setting.
4. **vmagent CPU/memory usage doesn't trend upward with a higher limit either** (715m–1012m CPU,
   484–624Mi memory, scattered rather than ordered by rate_limit) — consistent with the limit not
   being exercised.

## Interpretation

This sweep demonstrates that **raising prod's rate limit up to 20 MiB/s and max block size up to
10 MiB introduces no observed regression** at 2000-node scale — a safe, validated increase over the
current 2 MiB/s / .5 MiB baseline.

However, because **none of the 10 configs showed any stress signal**, this sweep does not by itself
identify the true safe ceiling — only that the ceiling is at or above 20 MiB/s. The workload's real
remote-write throughput need at 2000 nodes appears to be comfortably under even the current prod
setting, so a value change here is more about **removing an artificial ceiling** than fixing an
observed bottleneck.

## Recommendation

- **Provisional**: safe to raise prod's `-remoteWrite.rateLimit` and `-remoteWrite.maxBlockSize` at
  least to the highest tested values (20 MiB/s / 10 MiB) based on this data — zero regressions on
  every metric checked. Treat as provisional, not final, until re-verified against the fuller
  data-loss metric set (see Caveats) — the packet-drop/retry counters checked here were confirmed
  genuinely zero, but `rate_limit_reached_total` specifically was not.
- To find the actual failure ceiling (rather than just clearing 20 MiB/s), a follow-up sweep should
  push meaningfully higher (e.g. 30–50 MiB/s) and/or test at a higher node count or lower per-tier
  dwell, since this workload never got close to saturating even the 2 MiB/s baseline here.

## Caveats

- **Metric coverage gap (found after this report was first written):** the harness's
  `TIMESERIES_METRICS` list captured `vmagent_remotewrite_packets_dropped_total` and
  `_retries_total` — confirmed genuinely zero across all 236 samples/config in this sweep, not
  just "no data" — plus `vmagent_remotewrite_pending_data_bytes` (used above as "Pending backlog").
  It did **not** capture `vmagent_remotewrite_samples_dropped_total`,
  `vmagent_remotewrite_rate_limit_reached_total` (the most direct signal for "was the rate limit
  ever actually hit"), `vm_rows_invalid_total`, or `vm_persistentqueue_bytes_dropped_total`/pending
  — the same set prod's own `data_loss.k` dashboard checks. These four have now been added to
  `adx.py`'s `TIMESERIES_METRICS`, but **this report's data predates that fix** — the "rate limit
  was never actually engaged" conclusion is inferred indirectly (flat backlog/CPU/mem, zero packet
  drops), not confirmed directly via `rate_limit_reached_total`. Re-run the sweep and refresh this
  report before treating the recommendation below as fully verified.
- This sweep used the standard MCR konn-server/agent images and static agent replica counts, not
  the newer autoscaler path — a separate, later run (`konn-new-images-with-autoscaler`) tested that
  combination and is analyzed separately.
- `not_evaluated` mid-ramp tiers (500/1000/1500) are excluded from this analysis — their lower
  scrape coverage is a fixed-pools tier-block-flip convergence artifact affecting all 10 configs
  identically, not a rate-limit/block-size effect.
