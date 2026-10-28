"""Kubernetes objects for the Agent Sandbox benchmark.

Upstream releases are pinned by URL and SHA-256. The agent-sandbox controller runs as one instance with throughput
settings (worker counts, warm-pool refill, separate watch connection, no per-object events). Sandbox pods land on
simulated KWOK nodes, so the benchmark loads the control plane (API server, etcd, controllers, scheduler) without a
data plane.
"""

import copy
import json
import os

import yaml

AGENT_SANDBOX_VERSION = "v1.0.7"
AGENT_SANDBOX_URL = ("https://github.com/kubernetes-sigs/agent-sandbox/releases/download/"
                     f"{AGENT_SANDBOX_VERSION}/sandbox-with-extensions.yaml")
AGENT_SANDBOX_SHA256 = "136c10c9347cb5a6740b351444cae82f404e883c3f520272257ba785f2af0da8"
KWOK_VERSION = "v0.8.0"
KWOK_URL = f"https://github.com/kubernetes-sigs/kwok/releases/download/{KWOK_VERSION}/kwok.yaml"
KWOK_SHA256 = "a4c16e6431e382dcb5c1903139344b7a68652f16a6460337fe17a678a426f405"
KWOK_STAGE_URL = f"https://github.com/kubernetes-sigs/kwok/releases/download/{KWOK_VERSION}/stage-fast.yaml"
KWOK_STAGE_SHA256 = "2f28d95564ec43056c0873f7a25ac7d2a5bba4c8496c72f8b3ee73fd4f54ee24"

CONTROLLER_NAME = "agent-sandbox-controller"
CONTROLLER_ARGS = [
    "--leader-elect=true", "--extensions",
    "--sandbox-concurrent-workers=200", "--sandbox-claim-concurrent-workers=150",
    "--sandbox-warm-pool-concurrent-workers=4", "--sandbox-template-concurrent-workers=1",
    "--sandbox-warm-pool-max-batch-size=1000", "--sandbox-warm-pool-max-refill-rate=100",
    "--api-connections=4", "--cache-label-selectors", "--separate-watch-connection",
    "--disable-sandbox-events=true", "--disable-claim-events=true", "--disable-claim-observability-annotations=true",
]
POOL_NAMESPACE = "sbx-p{}"
POOL_NAME = "wp"
TEMPLATE_NAME = "t"
GENERATOR_NAMESPACE = "sbx-load"
GENERATOR_NAME = "sbx-load"
GENERATOR_IMAGE = "mcr.microsoft.com/azurelinux/base/python:3.12"
KWOK_NODE_LABEL = "agent-sandbox-benchmark/kwok"
HERE = os.path.dirname(os.path.abspath(__file__))


def controller_docs(release_docs, node_selector, cpu_limit="12", memory_limit="8Gi"):
    """The agent-sandbox release with the controller's arguments, resources and placement set."""
    docs = copy.deepcopy(release_docs)
    found = False
    for d in docs:
        if d.get("kind") == "Deployment" and d["metadata"]["name"] == CONTROLLER_NAME:
            spec = d["spec"]["template"]["spec"]
            spec["nodeSelector"] = dict(node_selector)
            container = spec["containers"][0]
            container["args"] = list(CONTROLLER_ARGS)
            container["resources"] = {"requests": {"cpu": "1", "memory": "512Mi"},
                                      "limits": {"cpu": cpu_limit, "memory": memory_limit}}
            found = True
    if not found:
        raise ValueError(f"release has no {CONTROLLER_NAME} Deployment")
    return docs


def kwok_docs(release_docs, node_selector):
    """The KWOK release, placed on the given nodes, with enough parallelism for thousands of pods per second."""
    docs = copy.deepcopy(release_docs)
    for d in docs:
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "kwok":
            config = yaml.safe_load(d["data"]["kwok.yaml"])
            config.setdefault("options", {}).update(
                {"podPlayStageParallelism": 64, "nodePlayStageParallelism": 16, "nodeLeaseParallelism": 16})
            d["data"]["kwok.yaml"] = yaml.safe_dump(config, sort_keys=False)
        if d.get("kind") == "Deployment":
            spec = d["spec"]["template"]["spec"]
            spec["nodeSelector"] = dict(node_selector)
            spec["containers"][0]["resources"] = {"requests": {"cpu": "2", "memory": "2Gi"},
                                                  "limits": {"cpu": "8", "memory": "8Gi"}}
    return docs


def kwok_nodes(count, pods_per_node):
    """Simulated nodes that accept the Sandbox template's pods (its kata node selector and toleration)."""
    nodes = []
    for i in range(count):
        name = f"kwok-{i}"
        capacity = {"cpu": "1000", "memory": "4Ti", "pods": str(pods_per_node), "ephemeral-storage": "10Ti"}
        nodes.append({
            "apiVersion": "v1", "kind": "Node",
            "metadata": {
                "name": name,
                "annotations": {"kwok.x-k8s.io/node": "fake", "node.alpha.kubernetes.io/ttl": "0"},
                "labels": {"type": "kwok", KWOK_NODE_LABEL: "true", "kubernetes.io/os": "linux",
                           "kubernetes.io/arch": "amd64", "kubernetes.io/hostname": name,
                           "kubernetes.azure.com/kata-vm-isolation": "true", "kubernetes.azure.com/managed": "false"}},
            # A provider ID outside Azure makes the cloud provider treat the node as unmanaged and leave it alone.
            "spec": {"providerID": "kwok://" + name,
                     "taints": [{"key": "kata", "value": "enabled", "effect": "NoSchedule"}]},
            "status": {"allocatable": capacity, "capacity": capacity},
        })
    return nodes


def sandbox_template():
    with open(os.path.join(HERE, "config", "sandbox-template.json"), encoding="utf-8") as f:
        src = json.load(f)
    return {"apiVersion": src["apiVersion"], "kind": src["kind"], "spec": src["spec"]}


def pool_docs(count, replicas_per_pool):
    """count namespaces, each with the Sandbox template and a warm pool of replicas_per_pool Sandboxes."""
    docs = []
    template = sandbox_template()
    for i in range(count):
        ns = POOL_NAMESPACE.format(i)
        t = copy.deepcopy(template)
        t["metadata"] = {"name": TEMPLATE_NAME, "namespace": ns}
        docs += [{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns}}, t,
                 {"apiVersion": "extensions.agents.x-k8s.io/v1beta1", "kind": "SandboxWarmPool",
                  "metadata": {"name": POOL_NAME, "namespace": ns},
                  "spec": {"replicas": replicas_per_pool, "sandboxTemplateRef": {"name": TEMPLATE_NAME}}}]
    return docs


def phase_name(rate):
    return f"rate-{rate:g}".replace(".", "-")


def plan(run_id, pool_count, rates, duration_seconds, warmup_seconds, dwell_seconds, seed=1):
    """The generator's plan: one Poisson phase per rate, in order, over every pool. duration_seconds is the
    measured time per rate; each phase runs warmup_seconds longer, and the warmup is left out of the metrics."""
    return {
        "runId": run_id,
        "pools": [{"namespace": POOL_NAMESPACE.format(i), "name": POOL_NAME} for i in range(pool_count)],
        "phases": [{"name": phase_name(r), "kind": "poisson", "rate": float(r),
                    "durationSeconds": duration_seconds + warmup_seconds, "warmupSeconds": warmup_seconds,
                    "dwellSeconds": dwell_seconds} for r in rates],
        "readyTimeoutSeconds": 60, "requestTimeoutSeconds": 30, "teardownTimeoutSeconds": 120,
        "drainTimeoutSeconds": 300, "poolReadyFraction": 0.95, "poolReadyTimeoutSeconds": 900,
        "maxInflight": 2000, "workers": 64, "seed": seed,
    }


def generator_docs(plan_doc, generator_source, node_selector, image=GENERATOR_IMAGE):
    """Namespace, RBAC, ConfigMap and pod that run the generator in the cluster."""
    ns, name = GENERATOR_NAMESPACE, GENERATOR_NAME
    rules = [
        {"apiGroups": ["extensions.agents.x-k8s.io"], "resources": ["sandboxclaims"],
         "verbs": ["create", "get", "list", "watch", "delete"]},
        {"apiGroups": ["extensions.agents.x-k8s.io"], "resources": ["sandboxwarmpools"], "verbs": ["get", "list", "watch"]},
        {"apiGroups": ["agents.x-k8s.io"], "resources": ["sandboxes"], "verbs": ["get", "list", "watch"]},
        {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch"]},
    ]
    return [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns}},
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": name, "namespace": ns}},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole", "metadata": {"name": name}, "rules": rules},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding", "metadata": {"name": name},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": name},
         "subjects": [{"kind": "ServiceAccount", "name": name, "namespace": ns}]},
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name, "namespace": ns},
         "data": {"generator.py": generator_source, "plan.json": json.dumps(plan_doc, indent=1)}},
        {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": ns, "labels": {"app": name}},
         "spec": {"serviceAccountName": name, "nodeSelector": dict(node_selector), "restartPolicy": "Never",
                  "terminationGracePeriodSeconds": 5,
                  "containers": [{"name": "generator", "image": image,
                                  "command": ["python3", "/opt/sbx/generator.py", "--plan", "/opt/sbx/plan.json",
                                              "--out", "/results"],
                                  "resources": {"requests": {"cpu": "4", "memory": "4Gi"},
                                                "limits": {"cpu": "8", "memory": "8Gi"}},
                                  "volumeMounts": [{"name": "code", "mountPath": "/opt/sbx"},
                                                   {"name": "results", "mountPath": "/results"}]}],
                  "volumes": [{"name": "code", "configMap": {"name": name}}, {"name": "results", "emptyDir": {}}]}},
    ]
