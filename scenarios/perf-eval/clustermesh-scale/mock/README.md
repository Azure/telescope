# Vendored mock-cluster mesh deploy scripts

These scripts are **vendored** from the companion `mock-clustermesh/deploy/` tree so
the telescope pipeline is self-contained (the AzDO agent checks out only the
telescope repo). They are invoked by
`steps/topology/clustermesh-scale-mock/deploy-mock-layer.yml`.

| Script | Purpose |
|--------|---------|
| `provision-kwok-layer.sh` | Per-cluster deployer: installs KWOK, creates N virtual nodes (per-cluster podCIDRs + distinct node IPs), deploys one mock-cilium-agent per node (Prometheus on :9962, clustermesh consume secrets), inherits the control-plane subset of the managed cilium-config. |
| `attrition-check.sh` | Non-fatal liveness check: compares Running mock-cilium-agents vs KWOK nodes; always exits 0. |

## Keeping these in sync

The source of truth is `mock-clustermesh/deploy/`. When that changes, re-vendor:

```bash
cp mock-clustermesh/deploy/provision-kwok-layer.sh \
   mock-clustermesh/deploy/attrition-check.sh \
   telescope-upstream/scenarios/perf-eval/clustermesh-scale/mock/
```

## Prerequisite: the mock-cilium-agent image

`provision-kwok-layer.sh` deploys `${ACR_HOST}/mock-cilium-agent:${AGENT_TAG}`. The
`deploy-mock-layer.yml` step **automatically grants the cluster's kubelet identity
AcrPull** on `MOCK_ACR_HOST` (the ACR is private — same-subscription does not
auto-grant pull), so you only need to:

1. Build + push the image to an ACR in the **same subscription** as the test clusters
   (build instructions: `mock-clustermesh/cmd/mock-cilium-agent/`), and
2. Set the `MOCK_ACR_HOST` / `MOCK_AGENT_TAG` pipeline variables.

If you use a different access model (cross-sub ACR, anonymous pull, or an
imagePullSecret), the auto-attach is non-fatal and the deploy step's readiness gate
still validates that the agents actually came up.

See `../MOCK-MODE.md` for the full integration overview.
