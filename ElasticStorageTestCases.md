# Elastic Storage End-to-End Test Plan
This document is the test plan of the Elastic Storage scale-out and scale-in features, including trigger
conditions, test setup, and E2E test cases (happy path, negative, and feature-rollback) for both
flows.


## 1. Overview

**Scale-out** replicates a "hot" blob from its normal 2 managed copies out to a larger target total
(default 6) when it gets too much read traffic. It triggers when:
- Region level `ACR_Feature_ElasticStorageEnabled` and registry level `Feature_ElasticStorageEnabled` feature flag is on;
- Premium registry;
- Blob has in-region replication ready;
- Egress for a single blob, from a single storage account, exceeds `EgressBytesThreshold` bytes
  within one `EgressAggregationWindowSeconds` window.

**Scale-in** is meant to remove the extra elastic replicas once a blob has cooled back down.
It triggers when:
- Blob is scaled out by the elastic storage scale-out process;
- Pass `ScaleInCooldown` (default 14 days) gate;
- Blob is verified cold: total egress summed across **all** replica storage accounts for the blob over the
  last 14 days is under `ACR_ElasticStorage_ScaleInEgressThresholdBytes` (1 TB by default).


## 2. Test setup

**Test image / data**
- Create a Premium registry and turn on registry level feature flag via acis action
- Use a test image with a single large layer, ~1 GB, pushed to a test registry so its blob has
  no pre-existing elastic replicas.
- Lower `ACR_ElasticStorage_EgressBytesThreshold` to **5 GB** so **5 pulls** of the 1 GB layer within
  one aggregation window cross the threshold (keep `ACR_ElasticStorage_EgressAggregationWindowSeconds`
  at its default, e.g. 300s/5min).
- Set `ACR_ElasticStorage_ScaleInCooldown` to lower value instead of the 14-day default, so
  cooldown-gate tests complete in-session instead of over two weeks.

**Config overrides for this test pass**

The [test configuration][elastic-storage-test-config] provides the overrides shared by scale-out and scale-in.

| Key | Default | Test value |
|---|---|---|
| `ACR_Feature_ElasticStorageEnabled` | `false` | `true` (scoped to the test regions) |
| `ACR_ElasticStorage_EgressBytesThreshold` | `2812500000000` (~2.8 TB) | `5368709120` (5 GB) |
| `ACR_ElasticStorage_ScaleInCooldown` | `14.00:00:00` (14 days) | `00:20:00` (20 min) |
| `ACR_AzureStorageQueueMaxVisibilityTimeout` | `7.00:00:00` (7 days) | `00:10:00` (10 min) |
| `ACR_ElasticStorage_CounterTtlSeconds` | `1209600` (14 days) | `1200` (20 min) |
| `ACR_ElasticStorage_ScaleInEgressThresholdBytes` | `1099511627776` (1 TB) | `3221225472` (3 GB) |
| `Layer_TableExpirationDelayTimeSpan` | `01:00:00` (1 h) | `00:02:00` (2 min) — Phase B→C cache-drain delay |
| `elasticStorageStatusBlobDeletedRetentionDays` | 365 | leave default (off the scale-in critical path) |

Observe tombstones before their shortened retention expires. The table-expiration delay is the scale-in
cache-drain interval.

**Mechanics**
- Drive 5 sequential or concurrent pulls of the 1 GB layer inside one aggregation window to cross
  the 5 GB threshold and trigger a claim.
- Watch `elasticstoragecounters` (egress accumulation) and `elasticstoragestatus` (doc id `"status"`,
  partition key `{digestEncoded}&{registryId}`) directly in Cosmos to confirm state transitions
  between steps, rather than relying on logs alone.
- Feature-flag scope the test to one region/registry so the rest of the fleet is unaffected.

## 3. E2E test cases

### 3.1 Scale-out

#### Happy path

**TC-SO-01 — Golden path: cold blob scales out**
- Setup: fresh 1 GB layer, no elastic replicas, flags on.
- Steps: pull the layer 5 times within 5 minutes.
- Expected:  
  During scale-out:
  
  1. GetBlob events get queued to the right stamp-based `elasticstoragequeue` (same stamp as the
     registry).
  2. `elasticstoragecounters` document for the window is created and accumulates egress after each
     pull.
  3. `elasticstoragestatus` document created (`id="status"`, partition key
     `{digestEncoded}&{registryId}`) with `status="sending-scaleout-message"` once accumulated
     egress ≥ 5 GB.
  4. Status transitions `sending-scaleout-message → scaling-out`; `scaleOutLeaseExpiredAt` stamped
     `now + lease duration`.
  5. 4 new `BlobLocationEntity` rows are created, each `IsElasticCopy=true` with `Active` status,
     each on a distinct storage account not already used by an existing copy.
  6. Existing replica reconciliation/expired-entity cleanup does **not** delete the new elastic
     rows as "excess" on its next pass over the same blob after scale-out. (repush the same blob to trigger this)
  7. Status transitions `scaling-out → scaled-out`; `replicaCopyCount=6`; `scaledOutAt` stamped.
  8. Scale-in message gets queued to `deferredindexingqueuelayerplatformops` with no expiration and
     the configured 10-minute test visibility timeout.
  9. Metric `LogBlobScaledOutMetric` emitted exactly once.
  10. Metric `LogScaleOutE2ELatencyMetric` emitted with a duration consistent with actual
      replication time (no anomalous multi-minute value).
  11. Metrics `QueueLag` and `QueueLength` emitted for `elasticstoragequeue`.
  12. No warning/error-level logs anywhere in the successful path.

  After scale-out:

  13. A pull of the blob succeeds and returns content whose digest matches the original, served
      from one of the new elastic accounts.  
  14. No errors or retries in pull operations caused by the scale-out process itself.  
  15. No stray/duplicate `elasticstoragecounters` or `elasticstoragestatus` documents exist for
      this digest (exactly one status doc; counter docs only for windows actually observed).  
  16. `elasticstoragecounters` document expires and is cleaned up after
      `ACR_ElasticStorage_CounterTtlSeconds`.

**TC-SO-02 — Idempotent re-trigger on an already-scaled-out blob**
- Setup: blob from TC-SO-01, already `scaled-out`.
- Steps: drive 5 more pulls to cross the threshold again.
- Expected:
  1. `lastHotAt` on the status document is refreshed to a newer timestamp.
  2. Still exactly one `elasticstoragestatus` document for this digest (no duplicate created).
  3. No message sent to `blobreplicationqueue` (queue depth unchanged by this event).
  4. No new `BlobLocationEntity` rows created; replica count remains 6 (2 managed + 4 elastic).
  5. `status` field remains `"scaled-out"`; `replicaCopyCount` remains 6.
  6. `LogBlobScaledOutMetric` and `LogScaleOutE2ELatencyMetric` is not emitted again for this event.

**TC-SO-03 — Blob stays hot while scale-out is still in flight (producer refuses; single holder)**
- Setup: fresh 1 GB layer, no elastic replicas, flags on.
- Steps:
  1. Cross the threshold once so the blob claims scale-out and transitions to `scaling-out`
     (lease stamped `now + lease duration`).
  2. Before that lease expires and before replication finishes, keep pulling the same blob so it
     crosses the egress threshold again one or more times.
- Expected:
  1. No additional `scaleoutblob` messages enqueued to `blobreplicationqueue` for this digest.
  2. The original delivery completes normally: exactly 4 new elastic rows, status transitions to
     `scaled-out`, `replicaCopyCount=6`.
  3. `LogBlobScaledOutMetric` fires exactly once despite the repeated threshold crossings.
  4. `elasticstoragecounters` keeps accumulating egress for the in-flight windows,
     but no counter state re-triggers a claim. `lastHotAt` is **not** advanced when status is `scaling-out`.
     It was stamped once at lease acquisition and only the `scaled-out` path refreshes it thereafter.

**TC-SO-04 — Multiple `scaleoutblob` messages while the lease is still live (consumer refuses; single holder)**
- Setup: fresh 1 GB layer, no elastic replicas, flags on. Drive one threshold crossing so cosumer pod A
  acquires the lease — the row is `scaling-out` with `scaleOutLeaseExpiredAt` stamped in the future —
  and hold A's replication in flight (not yet `scaled-out`).
- Steps: deliver the same `scaleoutblob` message and picked up by a second consumer pod B while the lease is still unexpired.
- Expected:
  1. Pod B drops the message and creates zero `BlobLocationEntity` rows and does not touch `blobLocation`.
  2. Pod A remains the sole holder and completes normally: exactly 4 new elastic rows,
     `scaling-out → scaled-out`, `replicaCopyCount=6`.
  3. `LogBlobScaledOutMetric` fires exactly once (from Pod A).

**TC-SO-05 — Re-entry from `blob-deleted`: re-pushed digest goes hot again**
- Setup: a digest whose `elasticstoragestatus` document is at `status="blob-deleted"` (tombstoned by
  a prior delete cascade — `Ttl` set, `DeletedAt` stamped). Re-push the same digest so it's
  referenced again, no elastic replicas present.
- Steps: drive a threshold-crossing pull burst (5 pulls, same mechanics as TC-SO-01) against the
  re-pushed digest.
- Expected:
  1. The flow proceeds normally through to `scaled-out` (per TC-SO-01): 4 new elastic rows,
     `replicaCopyCount=6`.
  2. Still exactly one `elasticstoragestatus` document for the digest throughout (the tombstone is
     reused/reclaimed, not duplicated). The status document's `Ttl` set to -1 and `DeletedAt` removed.
  3. No exception thrown, no error-level logs from the re-entry.

**TC-SO-06 — Re-entry from `scaled-in`: cooled-down blob goes hot again and re-scales-out**
- Setup: scale out a blob and then scale in the blob, so`elasticstoragestatus` row at `status="scaled-in"`
  and `blobLocation` holding only the 2 managed copies.
- Steps: resume pull traffic — drive a threshold-crossing pull burst (5 pulls, same mechanics as
  TC-SO-01) against the cooled-down digest.
- Expected:
  1. The flow proceeds normally through to `scaled-out` (per TC-SO-01): 4 new elastic rows,
     `replicaCopyCount=6` (2 surviving managed + 4 fresh elastic).
  2. No exception thrown, no error-level logs from the re-entry.

**TC-SO-07 — Registry moved to another stamp can scale out and scale in**
- Setup:Create a Premium registry on source stamp A with the regional and registry-level elastic-storage
  feature flags enabled. Push a fresh 1 GB layer with no elastic replicas.
- Steps:
  1. Trigger pull traffic — drive a threshold-crossing pull burst on Stamp A.
  2. Move the registry from stamp A to stamp B.
  3. Wait for 15m, the pull the layer again.
- Expected:
  1. After step 1, verify scalein message is queued to stamp A's `deferredindexingqueuelayerplatformops`.
  2. After step 3, verify that getblob events are queued to stamp B's `elasticstoragequeue` and handled by Stamp B's `ElasticStorageService` pods.
  3. The scale-in check queued on stamp A before migration is processed on stamp A, not moved to stamp B.
     After the blob remains cold through the cooldown and verification windows, that pending work completes cleanup.

**TC-SO-08 — Registry SKU downgraded from Premium to Standard cleans up elastic blobs**
- Setup: a Premium registry with a `scaled-out` 1 GB layer (`replicaCopyCount=6`: 2 managed + 4
  elastic), flags on. Confirm the scale-in message for this digest is already queued on
  `deferredindexingqueuelayerplatformops`.
- Steps:
  1. Downgrade the registry SKU from Premium to Standard.
  2. Wait for the downgrade to be processed and the elastic replicas to be cleaned up.
  3. Let the previously queued scale-in message become visible and get processed.
- Expected:
  1. After the downgrade is processed, the 4 elastic `BlobLocationEntity` rows are removed and
     the 2 managed copies remain active; `replicaCopyCount=2`.
  2. Pulls of the blob continue to succeed from the 2 managed copies with content matching the
     original digest. No more elastic replication occurs even if the blob becomes hot again.
  3. When the queued scale-in message runs against the already-cleaned-up digest, it completes
     without error — no exception thrown, no error-level logs, and the message is acked (not
     dead-lettered).

#### Concurrency tests

**TC-SO-09 — Producer claim race: concurrent hot events, exactly one advances to `sending-scaleout-message` (409/412)**
- Setup: drive multiple `getblob` events for the **same** digest so their egress increments all
  cross the threshold in the same window, and get them picked up concurrently by different
  `ElasticStorageService` pods.
  Exercise both starting points:
  - (a) **No status row yet** (first-ever scale-out): each pod reads null → `CreateInitialStatusAsync`.
  - (b) **Existing eligible row** (e.g. `failed-scale-out` / `scaled-in` / `blob-deleted`): each pod
    reads the same snapshot → `ClaimForScaleOutAsync`.
- Expected:
  1. (a) Exactly one `CreateItemAsync` insert succeeds → `Acquired`, logs `"Claimed initial scale-out
     for ({registryId},{digest}); status set to sending-scaleout-message."`; every other pod's insert
     **409**s → `AlreadyInProgress`, logs `"Lost initial-create race for ({registryId},{digest});
     another worker owns the claim."`.
  2. (b) Exactly one If-Match `ReplaceItemAsync` succeeds → `Acquired`, logs `"Reclaimed scale-out for
     {registryDigest}; status changed from {prev} to sending-scaleout-message."`; every other pod's
     replace **412** (or 409) → `AlreadyInProgress`, logs `"Lost scale-out claim race for
     {registryDigest} ({code}); another worker took ownership."`.
  3. The status row advances to `sending-scaleout-message` **exactly once**; `LastHotAt`, `Ttl=-1`,
     `DeletedAt=null` are set by the winner only.
     (Note: If the blob is consistently hot, before the scaling-in lease acquired, there will be multiple messages
     sent to downstream.)

**TC-SO-10 — Two consumers race the same delivery; only one consumer wins the lease**
- Setup: fresh 1 GB layer, no elastic replicas, flags on; ≥2 `RepositoryService` pods.
- Steps: Get two deliveries of the same digest's `scaleoutblob` message picked up by two different
   `RepositoryService` pods at (as close to) the same instant as possible, both while the status
   document is still `sending-scaleout-message` — e.g. publish the message multiple times, 
   so both pods dequeue before either has updated the row.
- Expected:
  1. Both pods read the same `sending-scaleout-message` snapshot and both call
     `TryAcquireScaleOutLeaseAsync`. Exactly one pod's If-Match replace succeeds (logs "Acquired
     scale-out lease..."); the other's `ReplaceItemAsync` call fails with 412, logged
     as a warning ("Lost scale-out lease race for {digest} (...); another delivery owns it."), and
     returns `false` — no exception thrown.
  2. Exactly one set of 4 new elastic `BlobLocationEntity` rows is created — total replica count
     converges to 6 (2 managed + 4 elastic), not more.
  3. No error-level logs anywhere in this flow — a lost lease race is expected, non-error outcomes.

**TC-SO-11 — Scale-out re-entry races an in-flight scale-in**
- What is racing: a digest that is currently `scaled-out` gets a fresh pull spike (re-heat) at the
  same time a scale-in cycle is running against it. Both sides issue **filter-predicate PATCHes on
  the one status document**, but they target different things, and what they contend for depends on
  which scale-in step the re-heat lands next to:
  - **Scale-in side** — Phase B step 1e's filter PATCH now conditions on **both** status **and**
    cold-ness: `c.status IN ('scaled-out', 'failed-scale-out', 'failed-scale-in', 'blob-deleted',
    'scaling-in') AND c.lastHotAt < @cooldownCutoff` → `scaling-in`.
    So it 412s if the status moved out of the eligible set **or** the blob is freshly hot
    (`lastHotAt >= cutoff`) at the instant the write executes. 
  - **Scale-out side** — re-heat crosses the threshold → While status is `scaled-out` and blob hot again,
    the scaleout process will just update `lastHotAt`.
- Setup: induce both windows against a fresh `scaled-out` 1 GB layer (flags on):
  - (a) **pre-marker** — re-heat lands while the row is still `scaled-out`, around step 1e.
  - (b) **post-marker during drain** — re-heat lands after step 1e wrote `scaling-in` (elastic rows
    `Expired` by 1f, `DeleteElasticBlob` in flight in Phase C/D).
- Expected:
  1. (a) The scale-out re-heat is a `lastHotAt` bump, and step 1e's predicate gates on `lastHotAt`,
     so the bump **does** decide the outcome — the two commit orderings now diverge:
     - refresh commits first (`lastHotAt = now`) → when step 1e evaluates, the live row is still
       `scaled-out` but `lastHotAt` is **not** `< cutoff`, so the predicate fails → **412, no marker
       written, no `blobLocation` rows Expired**. Scale-in requeues the scalein message for next cycle
       of cold verification; the blob stays `scaled-out`.
     - step 1e commits first (blob genuinely cold at that instant, `lastHotAt < cutoff`) → `scaling-in`
       is written; the later refresh's `c.status='scaled-out'` filter no longer matches → **412,
       ignored** (best-effort freshness bump; logs "Skipped lastHotAt refresh for {…}; row is no longer
       scaled-out"). `lastHotAt` stays old. The row is now `scaling-in` and elastic blobs marked as Expired.
  2. (b) Now the row is `scaling-in`, so `ClaimScaleOutAsync` hits the `default` branch →
     `ClaimForScaleOutAsync` (If-Match). This **is** a real status-transition race against Phase D
     step 2d's count-based finalize (`c.status='scaling-in'` → `scaled-in`/`scaled-out`); the single
     document serializes the two writes:
     - scale-out claim wins → `sending-scaleout-message`; the consumer counts only **Active** elastic
       copies (0, since 1f Expired them) and replicates 4 **fresh** copies → `scaled-out`. Phase D 2c
       still deletes the old `Expired` rows; 2d's status update now 412s and ack the message.
     - scale-in finalize wins → `scaled-in`; the scale-out `ClaimForScaleOutAsync` If-Match 412s →
       `AlreadyInProgress`. The hot egress counter persists, so the **next** threshold crossing
       re-reads `scaled-in` (claimable) and reclaims it — the re-heat is not lost.


#### Negative cases

**TC-SO-N01 — No status document (producer didn't initialize it)**
- Setup: manually enqueue a `scaleoutblob` message for a digest with no `elasticstoragestatus` row.
- Expected:
  1. Log matches `"No elastic-storage status document for {registryDigest}; producer did not
     initialize it. Dropping."`.
  2. No `BlobLocationEntity` rows created.
  3. The message is acked (deleted), not routed to the dead-letter queue.
  5. No `elasticstoragestatus` document is created as a side effect of the drop.

**TC-SO-N02 — Already at elastic-copy target**
- Setup: pre-seed 4 active `IsElasticCopy=true` rows (target already met) before triggering, but with status != `scaled-out`
- Steps: cross the threshold as normal.
- Expected:
  1. Log matches `"...already has 4 elastic copy/copies (target 4, total 6, managed 2); skipping
     replication and marking scaled-out."`.
  2. No new `BlobLocationEntity` rows created (count remains 4 elastic + 2 managed = 6).
  3. No replication calls are made.
  4. Status transitions directly to `scaled-out` with `replicaCopyCount=6`.
  5. `LogBlobScaledOutMetric` and `LogScaleOutE2ELatencyMetric` is emitted and no error-level logs emitted.

**TC-SO-N03 — Blob deleted between claim and consume**
- Setup: delete the blob (drop refcount to 0) after the producer(elasticStorageService) claims 
but before the consumer(repositoryservice) processes the message.
- Expected:
  1. Log matches `"...no longer referenced; skipping elastic replication. The delete cascade will
     transition the row to blob-deleted."`.
  2. No new `BlobLocationEntity` rows created.
  3. The status document is left in whatever state lease acquisition set (`scaling-out`) — it is
     not itself marked `scaled-out` or `failed-scale-out` by this code path.
  4. Message acked, no exception thrown.
  5. The independent delete cascade subsequently transitions the row to `blob-deleted` with the
     tombstone TTL set, confirming the two code paths don't race into an inconsistent final state.

**TC-SO-N04 — Scaled-out transition lost (412 race/5xx error)**
- Setup: force a concurrent writer to advance the status row between replication completing and
  the `TryMarkScaledOutAsync` If-Match write.
- Expected:
  1. Log matches `"Elastic copies for {registryDigest} were created but the transition to
     scaled-out was lost. A subsequent scale-out delivery will reconcile."`.
  2. Status document remains at whatever the concurrent writer set it to.
  3. The replica rows physically exist despite the status not reflecting it yet.
  4. `LogBlobScaledOutMetric` and the E2E latency metric still fire even though the persisted
     status update was lost (the code emits them unconditionally since the elastic blobs are created) —
     this is understood as a known metric/state mismatch, not treated as a bug.
  5. A subsequent redelivery (or hot-detection cycle) reconciles the row to `scaled-out` with the
     correct `replicaCopyCount`, without creating duplicate replicas.

**TC-SO-N05 — Unhandled exception mid-processing**
- Setup: inject a transient failure (e.g. simulated Cosmos throttling) partway through
  `HandleScaleOutBlobAsync`.
- Expected:
  1. `LogOperationFail` logged with the exception details.
  2. The exception propagates (rethrown) out of the method.
  3. The message's dequeue count increments and it becomes visible again for retry after the
     visibility timeout.
  4. After `maxDequeueCount` failed retries, the message is routed to the dead-letter queue.
  5. Any replication tasks that completed before the injected failure are correctly counted by the
     next retry's recount logic rather than being re-created (no duplicates).
  6. The failure is contained to this one message — the consumer process itself does not crash or
     stop processing other messages.

**TC-SO-N06 — Repositoryserice crash before enqueue (orphaned `sending-scaleout-message` row)**
- Setup: fresh 1 GB layer, no elastic replicas, flags on. Timing an actual pod kill to land exactly
  between the Cosmos claim write and `SendScaleOutAsync` isn't reliably reproducible — the whole
  window is milliseconds — so mock the crash directly instead of racing it: manually write an
  `elasticstoragestatus` document for the digest with `status="sending-scaleout-message"` (a valid
  ETag, `Ttl=-1`, `DeletedAt=null` — the same shape `CreateInitialStatusAsync` produces), and confirm
  zero `scaleoutblob` messages exist on `blobreplicationqueue` for this digest.
- Steps:
  1. Confirm the seeded state: one `elasticstoragestatus` doc at `sending-scaleout-message`, no
     matching message anywhere on `blobreplicationqueue` — this is the ghost row, mocked directly
     rather than timed against a real crash.
  2. There is nothing to redeliver — no message was ever enqueued for this claim, so there's no
     queue-redelivery path that applies here. Instead, drive a fresh threshold-crossing pull burst
     (5 pulls, same mechanics as TC-SO-01) against the same digest, exactly as a real second hot-blob detection
     would.
- Expected:
  1. ElasticStorageService should be able to detect the blob as hot blob and send hot blob event to blobreplicationqueue.
  2. The flow proceeds normally from there through to `scaled-out` (per TC-SO-01) — the ghost row
     self-heals via the fresh hot-blob detection rather than staying stuck.
  3. Still exactly one `elasticstoragestatus` document for the digest throughout (no duplicate/
     orphan doc created by the reclaim).
  4. No exception thrown, no error-level logs from the reclaim.

**TC-SO-N07 — Lease reclaim after a crashed holder**
- Setup: fresh blob; ability to kill the consumer pod mid-replication.
- Steps: let a delivery acquire the lease (`scaling-out`) and kill the pod before it completes;
  redeliver the message after `scaleOutLeaseExpiredAt` has passed.
- Expected:
  1. First delivery transitions status to `scaling-out` and stamps `scaleOutLeaseExpiredAt = now +
     leaseDuration`.
  2. No `scaled-out` transition is recorded from the killed delivery.
  3. Redelivery after the lease expiry successfully calls `TryAcquireScaleOutLeaseAsync` and
     re-stamps a fresh lease (log confirms lease acquired).
  5. Final elastic copy count equals exactly 4 (the target) — no duplicates from partial work by
     the crashed holder.
  6. Status transitions to `scaled-out` exactly once (final state), not more than once.
  7. Any partial rows left by the crashed holder are correctly counted toward
     `existingElasticCount` so the total still converges to 6, not 6 + leftover.


#### Feature rollback

**TC-SO-R01 — Regional flag off**
- Setup: use one of the registries already has scaling activity and set `ACR_Feature_ElasticStorageEnabled=false`
  in the registry region.
- Steps: drive normal (even high-egress) traffic by pulling the image.
- Expected:
  1. No `elasticstoragecounters` documents created despite high-egress traffic.
  2. No `elasticstoragestatus` document updated.
  3. No `blobreplicationqueue` entries with `Action="scaleoutblob"`. For any scaleout message
     already in the queue, they will be dropped without affecting the existing repositoryservice function.
  4. Already scaled out elastic blobs continue to serve the traffic until scaled in.
  5. Normal (non-elastic) replica reconciliation continues to function unaffected.
     Repushing the same blob will not clean up the elastic blobs.
  6. Turning back the regional flag on should process getBlob and scaleOutBlob events successfully.

**TC-SO-R02 — Per-registry flag off**
- Setup: region flag on, but a specific test registry opted out via `isRegistryElasticStorageEnabled`.
- Steps: drive normal (even high-egress) traffic by pulling the image. (Please note there is a 15m cache for the registry level feature flag.)
- Expected:
  1. The opted-out registry shows zero `elasticstoragestatus`/`elasticstoragecounters` documents
     despite high egress.
  2. A sibling registry in the same region without the override shows normal scale-out activity
     for equivalent traffic.
  3. Flipping the per-registry flag back on (after cache drain), causes subsequent
     hot traffic on that registry to correctly begin scaling out.

### 3.2 Scale-in

These 23 proposed E2E cases cover normal scale-in, concurrent activity, recovery, and rollback.
They are not executed test results. Cases marked **Acceptance gap** describe required behavior that the current
implementation does not reliably provide.

Contents:
- [Shared test setup](#2-test-setup)
- [Scale-in functional and lifecycle cases](#scale-in-functional-and-lifecycle-cases)
- [Scale-in concurrency cases](#scale-in-concurrency-cases)
- [Scale-in negative and recovery cases](#scale-in-negative-and-recovery-cases)
- [Scale-in feature rollback](#scale-in-feature-rollback)
- [Scale-in acceptance criteria](#scale-in-acceptance-criteria)

#### Scale-in functional and lifecycle cases

**TC-SI-01 - Golden path: cold blob returns to baseline**

- Setup: baseline fixture; no further hot or warm traffic.
- Steps: allow the initial 10-minute delay, remaining cooldown, cold check, and 2-minute drain to complete.
- Expected:
  1. First deferred check requeues for the remaining cooldown, preserving `OriginalMessageSentAt` and infinite TTL.
  2. Once cooldown elapses, the check is forwarded immediately to the platform-operations indexing queue with its
     standard 7-day TTL.
  3. Cold verification passes; status becomes `scaling-in`.
  4. Only elastic rows become `Expired`; managed and primary rows remain unchanged.
  5. A deferred `DeleteElasticBlob` message is sent with infinite TTL and the configured drain delay.
  6. Before drain completion, the expired copies still physically exist. Afterward, their blobs and location rows
     are removed; empty replica containers are cleaned up.
  7. Final state is `scaled-in`, with `replicaCopyCount=2` and no remaining elastic rows.
  8. Pulls still succeed and the content digest matches the original.
  9. Successful scale-in and reclaimed-copy metrics appear. Reported scale-in latency includes drain/backlog,
     not the intentional cooldown.

**TC-SI-02 - Still hot: restart cooldown from last hot detection**

- Setup: scaled-out blob with a pending check.
- Steps: produce a confirmed hot event before verification. Wait until the persisted `lastHotAt` advances,
  accounting for refresh throttling.
- Expected:
  1. No elastic copies are expired or deleted.
  2. The next check uses `lastHotAt` as its cooldown anchor, with visibility capped at 10 minutes.
  3. Subsequent hops preserve that anchor.
  4. After traffic stops and both coldness gates pass, normal scale-in completes.

**TC-SI-03 - Still warm: aggregate demand retains replicas**

- Setup: `lastHotAt` is older than cooldown, but qualifying recent counters total **more than 3 GB across
  multiple accounts**. Keep each account/window below the scale-out trigger.
- Steps: process the scale-in check, then stop traffic and allow the activity to age out.
- Expected:
  1. The first check retains all four elastic copies and requeues after the configured 10-minute interval.
  2. No new `lastHotAt` is fabricated merely because cumulative demand is warm.
  3. Once recent egress falls to or below the threshold, scale-in proceeds.

**TC-SI-04 - Lookback, TTL, and delayed events**

- Setup: controlled counters on both sides of the lookback boundary and scale-out timestamp.
- Steps: verify the query cutoff, then deliver a delayed event for an older request window.
- Expected:
  1. Current implementation uses `_ts >= max(now-cooldown, scaledOutAt)`, at Unix-second precision.
  2. Counter TTL is measured from the last document modification, not request start or first insertion.
  3. An updated old bucket can become query-visible again; explicitly measure whether it conservatively delays
     scale-in.
  4. Do not assume the cutoff removes the triggering burst if that same counter is updated after scale-out.

This case distinguishes the implemented `_ts` behavior from the spec's stronger "post-scale-out traffic only"
description.

**TC-SI-05 - Recover partial or failed cycles**

- Setup: separate cold fixtures in `failed-scale-out`, `failed-scale-in`, and `scaling-in`, with a mix of active
  and already-expired elastic rows.
- Steps: deliver a scale-in check.
- Expected:
  1. Existing expired rows count as outstanding cleanup, not as absent replicas.
  2. Remaining active elastic rows are expired; the delete is scheduled.
  3. Physical cleanup converges to baseline without touching managed copies.
  4. With **zero elastic rows**, the eligible status is finalized directly using the observed active replica
     count, without unnecessary counter queries or deletes. TC-SI-C07 covers a new scale-out racing this fast path.

**TC-SI-06 - Trim over-provisioning while hot or warm**

- Setup: two managed replicas plus six active elastic replicas, target total six. Exercise both the still-hot
  and still-warm branches.
- Steps: process the check and deferred deletion.
- Expected:
  1. Exactly two surplus elastic rows are selected deterministically and expired.
  2. Four active elastic copies remain; already-expired rows do not count toward the surplus.
  3. The trim does not first mark the blob `scaling-in`.
  4. After deletion, status remains `scaled-out`, total active replicas equal six, and a future cold check
     remains scheduled.
  5. Reclaimed-copy telemetry distinguishes trimming from a completed cold scale-in.

**TC-SI-07 - Re-scale-out and repeat the lifecycle**

- Setup: blob successfully scaled in by TC-SI-01.
- Steps: reheat it, verify a new scale-out, then stop traffic and let it cool again.
- Expected:
  1. Fresh elastic copies and a fresh cooldown check are created.
  2. The second scale-in completes without old messages deleting active copies from the new cycle.
  3. No leftover elastic rows or containers accumulate across cycles.

**TC-SI-08 - Pending scale-in completes on the source stamp after migration**

- Setup: a Premium registry on stamp A with a scaled-out 1 GB layer, two active managed replicas, and four
  active elastic copies. Enable the regional elastic-storage flag on both stamps and the registry-level flag,
  reusing TC-SO-07's migration setup.
- Steps:
  1. Confirm scale-out completed on stamp A and its scale-in check is pending on stamp A's
     `deferredindexingqueuelayerplatformops`. Record the registry/digest and message identity.
  2. Move the registry from stamp A to stamp B while that check is still pending.
  3. After cache refresh, verify reads route to B, then stop traffic and allow the original check's cooldown,
     cold verification, and cache-drain interval to complete.
- Expected:
  1. The original scale-in check remains on stamp A's queue and is processed by stamp A's workers; migration
     does not require moving or recreating it on stamp B.
  2. That pending work expires and deletes the old elastic copies despite the registry now residing on B.
     Primary and managed copies remain intact.
  3. Final state is `scaled-in`, with `replicaCopyCount=2` and no remaining elastic rows or blobs.
  4. Pulls through stamp B continue to succeed and return content matching the original digest.

**TC-SI-09 - SKU downgrade cleans up elastic copies before the pending cold check**

- Setup: an independent Premium registry with a scaled-out 1 GB layer, active elastic copies, and a pending
  scale-in check, reusing TC-SO-08's downgrade setup.
- Steps:
  1. Downgrade the registry from Premium to Standard and trigger the normal reconciliation workflow.
     Resolve the expected managed-replica baseline from the new SKU's replication policy.
  2. Verify all elastic copies become expired and their scheduled deletion completes after the cache-drain
     interval, before the previously queued scale-in check runs.
  3. Let the previously queued scale-in check become visible and process the already-cleaned-up blob.
- Expected:
  1. Downgrade reconciliation expires all elastic copies and its scheduled deletion removes their blobs and
     location rows without relying on the later cold check to initiate cleanup.
  2. The primary copy and the valid managed baseline for Standard remain available. Pulls succeed and return
     content matching the original digest; no new elastic scale-out occurs for the downgraded registry.
  3. The later scale-in check acknowledges without error, recreating elastic copies, or deleting surviving
     primary/managed copies. Final status is `scaled-in`, with `replicaCopyCount` matching the observed active
     managed-replica count and no remaining elastic rows.
  4. Do not assume that downgrade preserves two managed replicas; use the resolved replication-policy baseline.

#### Scale-in concurrency cases

**TC-SI-C01 - Reheat between cold verification and marker write**

- Setup: pause immediately before the conditional `scaling-in` write.
- Steps: refresh `lastHotAt`, then resume the marker write. Also test the reverse commit ordering.
- Expected:
  1. Refresh first: marker rejected; no replicas expired; **another cold check must remain scheduled**.
  2. Marker first: the later `scaled-out`-only refresh cannot overwrite the scale-in state. Subsequent hot
     events can re-enter scale-out.

> **Acceptance gap:** The current rejected-marker branch acknowledges without requeueing. Test future cleanup
> as well as immediate safety.

**TC-SI-C02 - Scale-out re-entry during cache drain**

- Setup: all old elastic rows are expired; physical deletion has not started.
- Steps: reheat the blob, create fresh active replicas, then process the old delete message.
- Expected:
  1. Old expired copies are reclaimed; new active copies remain untouched.
  2. Managed replicas remain intact throughout.
  3. Scale-in finalization does not overwrite the new scale-out's state with stale counts.
  4. The new scale-out schedules its own future check.

**TC-SI-C03 - Duplicate checks and duplicate deletes**

- Setup: at least two consumers; duplicate `ScaleInBlob` and `DeleteElasticBlob` deliveries.
- Steps: exercise concurrent processing and replay after completion.
- Expected:
  1. No active managed or primary copy is deleted.
  2. Duplicate expiration/deletion converges without resurrecting removed rows.
  3. Final status and count match storage reality.
  4. No unbounded message multiplication or unexpected DLQ growth.
  5. Do not require exactly-once attempt/reclaimed-copy metrics unless the implementation explicitly
     deduplicates them.

**TC-SI-C04 - Old delete message meets newly expired copies**

- Setup: keep an older delete message available while a later cycle or reconciliation freshly expires
  additional elastic rows.
- Steps: process the old delete before the newer rows' drain interval has elapsed. Repeat with the ordinary
  replicated-blob cleanup path.
- Expected: each copy receives its own full cache-drain interval; an old message must not authorize early
  deletion of newly expired copies.

> **Acceptance gap:** Current elastic deletion selects all expired elastic rows without checking their
> individual expiration age.

**TC-SI-C05 - Blob deletion races scale-in**

- Setup: pause scale-in during expiration or physical deletion.
- Steps: delete the manifest/blob references and let the full deletion cascade run; resume scale-in.
- Expected:
  1. Missing blobs/rows are handled idempotently.
  2. Scale-in finalization does not overwrite a concurrent `blob-deleted` tombstone.
  3. The tombstone carries the configured retention TTL.
  4. No orphan elastic storage remains. Later re-push/scale-out clears tombstone expiry before new
     replication work.

**TC-SI-C06 - Expiration conflict is not proof of expiration**

- Setup: force a location-row ETag conflict while the competing update leaves the row active.
- Steps: resume expiration and the following delete phase.
- Expected:
  1. When scale-in expiration and the deletion flow race to expire the same location row, one of the flows
     successfully persists `Expired` before physical deletion.
  2. The worker receiving 412 handles the conflict and continues processing the remaining work safely;
     the conflict does not abort cleanup.
  3. Verify the row's actual state and retry/reconcile unfinished work if it remains active; do not report
     successful cleanup while an unwanted active elastic copy survives.

> **Acceptance gap:** The current expiration helper treats every 412 as "already expired" without rereading
> the row.

**TC-SI-C07 - Zero-elastic-copy fast path races a completed scale-out**

- Setup: a cold-check fixture in `failed-scale-out`, with one primary copy, two active managed replicas,
  and zero elastic rows. Use a controlled barrier before fast-path finalization.
- Steps:
  1. Let the old cold check read the status and location rows, observing zero elastic copies and a baseline
     replica count of two. Pause before its fast-path finalization.
  2. Trigger a new scale-out for the same registry/digest and let it complete. Verify four fresh active
     elastic copies, status `scaled-out`, `replicaCopyCount=6`, and a newly scheduled scale-in check.
  3. Resume the old finalization using its original status/count snapshot. Exercise the real status-client
     predicate against Cosmos, not a mocked lost-race result.
- Expected:
  1. The old operation cannot publish `scaled-in` or the stale count of two over the newer lifecycle.
  2. Status remains `scaled-out`, `replicaCopyCount=6`, and all six active replicas remain intact.
  3. The old check does not emit a successful scale-in completion metric.
  4. After the new lifecycle cools, its scheduled check still performs cleanup rather than skipping it
     because of an incorrectly persisted `scaled-in` state.

> **Acceptance gap:** `TryMarkScaledInAsync` admits both the old snapshot's `failed-scale-out` status and the
> live row's new `scaled-out` status. Its finalization PATCH checks status membership, not ETag or lifecycle
> identity, so the stale operation can overwrite the newer status/count. This is separate from TC-SI-C02's
> deferred-delete finalization path.

#### Scale-in negative and recovery cases

**TC-SI-N01 - Missing, stale, or terminal status**

- Setup: independent fixtures for cold-check and already-drained delete messages.
- Steps:
  1. Deliver cold-check messages with missing status, `sending-scaleout-message`, `scaling-out`, `scaled-in`,
     and an unknown status.
  2. Separately deliver an already-drained delete with a missing status row.
  3. Deliver a cold check for a `blob-deleted` row with no elastic copies.
- Expected:
  1. No destructive cold-check work for the missing, stale, terminal, or unknown states in step 1; the message
     is acknowledged with the appropriate diagnostic.
  2. The already-drained delete still cleans up expired elastic copies, without creating a replacement
     status document.
  3. The `blob-deleted` row with no elastic copies retains its tombstone.

**TC-SI-N02 - Invalid deferred timestamps**

- Setup:
  - Elastic storage enabled in an isolated test registry; use the shared 20-minute cooldown and 2-minute drain.
    Test each action with missing and future timestamps, using a fresh fixture for each variant.
  - `ScaleInBlob`: status `scaled-out`, two managed and four elastic replicas active, with recent `lastHotAt`.
  - `DeleteElasticBlob`: a normal cold check has set `scaling-in` and expired the four elastic copies.
    Verify they still exist; each drain deadline is `ElasticCopyExpiredAt + 2 minutes`.
- Steps:
  1. Copy a valid event, then omit `OriginalMessageSentAt` or set it to UTC now + 10 minutes.
     Send it immediately visible on the deferred queue, before any delete drain deadline.
     Early visibility is deliberate fault injection; the invalid timestamp alone does not shorten queue delay.
  2. Follow rejected messages into the live indexing queue. For deletes, confirm indexing processes the message
     before the drain deadline; queue backlog must not mask premature deletion.
  3. On a separate fresh fixture, deliver a valid delete after its normal 2-minute drain but before
     a full 20-minute cooldown has elapsed.
- Expected:
  1. Malformed deletes cannot remove elastic blobs or location rows before their drain deadlines,
     or report successful early scale-in.
  2. Primary and managed copies remain intact.
  3. The valid control delete proceeds without another full cooldown.

> **Acceptance gap:** Deferred rejection forwards the message to the live indexing queue without delay.
> The indexing delete path checks neither the timestamp nor expiration age, so newly expired copies can be
> deleted too early.

**TC-SI-N03 - Crash or transient failure at each handoff**

- Setup: independent scale-in cycles with controlled failures.
- Steps: inject failure at these checkpoints:
  1. After some rows expire, before the delete enqueue.
  2. During the delete enqueue.
  3. After some physical deletes.
  4. After physical deletion, before final status update.
  5. After finalization, before message acknowledgement.
- Expected:
  1. Failures are observable and incomplete work remains retryable.
  2. Replays count actual surviving rows and finish only outstanding work.
  3. Storage 404s converge; 429/5xx failures are not mistaken for successful deletion.
  4. After recovery, cleanup completes without deleting managed copies.
  5. After all six allowed handler deliveries fail (including the initial attempt), the message is sent to
     the platform-operations indexing dead-letter queue and `LogBlobFailedScaleInMetric` is emitted.
     See TC-SI-N04 for manual replay after retry exhaustion.

**TC-SI-N04 - Retry exhaustion and manual replay**

- Setup: force repeated failures in both cold-check and physical-delete phases.
- Steps: exhaust the delivery budget, remove the fault, and replay the dead-lettered message.
- Expected:
  1. On the final allowed handler delivery, claimed scale-in states are best-effort parked at
     `failed-scale-in`; unrelated owner states are not overwritten.
  2. The message reaches the platform-operations indexing DLQ and failure telemetry is emitted.
  3. Failure of the status write does not suppress the original failure or dead-lettering.
  4. After removing the fault, replay completes cleanup.
  5. Do not assume an automatic retry sweeper exists merely because comments mention one.

**TC-SI-N05 - Scale-out succeeds but scheduling scale-in fails**

- Setup: allow `scaled-out` to persist, then fail the scale-in enqueue or crash before it.
- Steps: redeliver the original scale-out message without generating new hot traffic.
- Expected: recovery schedules a cold check, and the blob eventually scales in.

> **Acceptance gap:** The current scale-out consumer returns immediately for `scaled-out`, so this required
> recovery is not guaranteed.

#### Scale-in feature rollback

**TC-SI-R01 - Regional flag disabled at every phase**

- Setup: independent cycles positioned before dequeue in phases A, B, C, and D.
- Steps: disable the regional flag and verify configuration has propagated. Re-enable and replay retained work.
- Expected:
  1. New handler invocations reject scale-in work before elastic Cosmos/storage operations.
  2. Messages are sent to the dead-letter queue for later replay.
  3. Primary/managed copies remain available; already-expired elastic copies may remain physically stored
     while disabled.
  4. Re-enabling alone is not assumed to replay DLQ messages.
  5. Replay resumes cleanup without bypassing drain safety.
  6. Separately observe already-running handlers: an entry-time flag check is not cancellation of work
     already underway.

**TC-SI-R02 - Per-registry scale-out flag disabled**

- Setup: regional flag stays enabled; the registry already has scheduled scale-in work.
- Steps: disable only the registry-level flag and wait for eligibility-cache expiry.
- Expected:
  1. New eligible read events stop initiating scale-out for that registry.
  2. Existing documents are not expected to disappear immediately.
  3. Scheduled scale-in can still reclaim its elastic copies; the registry-level opt-out is not the regional
     scale-in kill switch.
  4. Other registries remain unaffected.