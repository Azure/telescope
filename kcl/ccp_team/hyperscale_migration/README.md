# Hyperscale Migration Benchmark

This Azure DevOps pipeline benchmarks migration of a fresh Standard-tier AKS
cluster to an H2, H4, or H8 control-plane profile.

## Workflow

1. Create an AKS 1.36 cluster in `westus2`.
2. Add a 20-node `Standard_D4_v3` pool for KWOK controllers.
3. Create and validate 2,000 simulated KWOK Nodes.
4. Install the Go migration verifier and ingest a fixed 2 GiB workload.
5. Start the selected H-profile migration and wait for completion.
6. Verify the ingested Kubernetes objects and etcd shard data.
7. Delete the resource group unless `keep_cluster` is enabled.

The workload consists of deterministic ConfigMaps, Secrets, and Pods so payload
integrity can be checked after migration. Each Pod is managed by a single-replica
Deployment. Etcd shard verification uses `etcdctl` to confirm replicated data.

## Payload Verification

The Go verifier generates each payload deterministically from the seed,
resource kind, object index, and payload block index. During ingestion it stores
the complete payload in the Kubernetes object and records its SHA-256 hash in a
manifest.

After migration, the verifier reads every object through the Kubernetes API,
hashes the complete stored payload again, and compares it with the manifest.
Missing, unexpected, or mismatched objects fail verification. This confirms
logical object correctness; the separate `etcdctl` step checks that shard data
is present on all etcd replicas.

## Parameters

- `scaling_size`: `H2`, `H4`, or `H8`.
- `keep_cluster`: retain the cluster after the run.

## Current Status

Cluster and KWOK provisioning are implemented. Migration-verifier installation,
workload ingestion, migration, waiting, and verification are currently
placeholder steps.

Generate the pipeline YAML with:

```bash
kcl run kcl/ccp_team/hyperscale_migration/ \
  -S output \
  -o kcl/ccp_team/hyperscale_migration/pipeline.yaml
```
