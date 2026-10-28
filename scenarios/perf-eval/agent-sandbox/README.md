# Agent Sandbox claim throughput

## Overview

Measures how many [Agent Sandbox](https://github.com/kubernetes-sigs/agent-sandbox) claims per second an AKS control
plane on the hyperscale profile (H8) serves within its latency objectives, with every claim served from a pre-warmed
Sandbox. Sandbox pods run on simulated [KWOK](https://github.com/kubernetes-sigs/kwok) nodes, so the load falls on the
control plane: the API server, etcd, kube-controller-manager (which deletes each claim's Sandbox and pod through its
garbage collector), kube-scheduler and the agent-sandbox controller.

## Infrastructure

- One AKS cluster with the H8 control plane (Kubernetes 1.36) and a system pool of 4 Standard_D16s_v5 nodes, created
  with the `azapi` module. The agent-sandbox controller, KWOK and the load generator run on that pool.
- 24 simulated KWOK nodes with room for 1,000 pods each.

## Workload

- agent-sandbox v1.0.7, one controller instance with up to 12 CPU and throughput settings: 200 Sandbox and 150 claim
  workers, warm-pool refill up to 100 Sandboxes per second per pool, a separate watch connection, and no per-object
  events or observability annotations.
- 4 warm pools of 750 Sandboxes each. The Sandbox template is upstream's `kata-aks` example.
- An in-cluster load generator (`modules/python/agent_sandbox/generator.py`, Python standard library only, run from
  `mcr.microsoft.com/azurelinux/base/python:3.12`) creates claims with Poisson arrivals at 50, 100, 150, 200, 250 and
  300 claims per second: a 60 s warmup, then 300 s measured per rate. Each claim is deleted 2 s after it is Ready.
  Before each rate the generator waits for the pools to be at least 95% full.

## Metrics

For each rate, over the claims that arrived after the warmup:

- latency from a claim's scheduled arrival to the moment the generator saw it Ready: p50, p90, p99 and max, with
  claims that never became Ready counted as infinitely slow;
- error rate, warm hit (the share of Ready claims served by a pre-warmed Sandbox) and achieved rate;
- teardown: from the claim delete returning until its pod is gone;
- generator lateness: from a claim's scheduled arrival until its create request was sent.

`verdict` is `pass` when at most 0.1% of claims fail, warm hit is at least 99%, teardown p99 is at most 30 s, p90 does
not drift by more than 10% (and 50 ms) from the first third of the window to the last, generator lateness p99 is at most
50 ms, and p99 latency is at most 1 s. `verdict_p90` applies the same checks with p90 latency at most 200 ms instead.
A run whose generator fell behind its schedule is marked `INVALID` in `reasons`.

## Results

`collect` writes one JSON line per rate with `rate`, `verdict`, `verdict_p90`, `reasons`, `metrics` (the numbers above),
`configuration` (versions, controller arguments and plan), `cloud_info`, `run_id` and `run_url`.

## Running it against any cluster

```bash
cd modules/python
python3 -m agent_sandbox.main configure --workdir /tmp/sbx --node_selector kubernetes.io/os=linux \
  --pools 2 --replicas_per_pool 50 --kwok_nodes 2 --pods_per_node 200 --controller_cpu 2
python3 -m agent_sandbox.main execute --workdir /tmp/sbx --node_selector kubernetes.io/os=linux \
  --run_id local --pools 2 --rates 5,10 --duration 20 --warmup 5
python3 -m agent_sandbox.main collect --workdir /tmp/sbx --run_id local --result_file /tmp/sbx/results.json
```
