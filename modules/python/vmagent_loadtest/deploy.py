"""Deployment helpers for all load test components."""

import json
import time
from pathlib import Path

import yaml

from .config import (
    FAKE_EXPORTER_DIR, FAKE_EXPORTER_IMAGE, FAKE_EXPORTER_NS,
    FAKE_EXPORTER_ROLES, KONN_AGENT_IMAGE, KONN_SERVER_IMAGE,
    KUBELET_SA_NAME, MANIFEST_DIR, VMAGENT_IMAGE,
    log,
)
from .utils import kubectl, kubectl_apply, render_template, retry, run


def ensure_namespace(kubeconfig: str, namespace: str) -> None:
    for _ in range(60):
        result = kubectl(kubeconfig, "get", "ns", namespace, "-o", "jsonpath={.status.phase}", check=False)
        if result.returncode != 0:
            break
        if result.stdout.strip() == "Terminating":
            log.info("  Waiting for namespace %s to terminate...", namespace)
            time.sleep(5)
            continue
        break
    result = run(
        ["kubectl", "--kubeconfig", kubeconfig, "create", "ns", namespace,
         "--dry-run=client", "-o", "yaml"]
    )
    run(["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"],
        input=result.stdout, capture=False)
    kubectl(kubeconfig, "label", "ns", namespace, "loadtest=true", "--overwrite", check=False)


@retry(max_attempts=3, backoff=5.0)
def deploy_konnectivity_server(kubeconfig: str, namespace: str, server_count: int = 1,
                                wait: bool = True) -> None:
    log.info("Deploying konnectivity-server in %s on control plane...", namespace)
    manifest = render_template(MANIFEST_DIR / "konnectivity-server.yaml", {
        "__NAMESPACE__": namespace,
        "__SERVER_IMAGE__": KONN_SERVER_IMAGE,
        "__SERVER_COUNT__": str(server_count),
    })
    kubectl_apply(kubeconfig, manifest)
    if wait:
        kubectl(kubeconfig, "-n", namespace, "rollout", "status",
                "deployment/konnectivity-server", "--timeout=120s")
        log.info("Konnectivity server ready in %s", namespace)
    else:
        log.info("Konnectivity server deployed (waiting for certs before readiness)")


def get_server_lb_ip(kubeconfig: str, namespace: str, timeout: int = 300) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = kubectl(
            kubeconfig, "-n", namespace, "get", "svc", "konnectivity-server",
            "-o", "jsonpath={.status.loadBalancer.ingress[0].ip}",
            check=False,
        )
        ip = result.stdout.strip()
        if ip:
            return ip
        log.info("  Waiting for LB IP in %s...", namespace)
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for konnectivity-server LB IP in {namespace}")


@retry(max_attempts=3, backoff=5.0)
def deploy_konnectivity_agents(kubeconfig: str, namespace: str, server_host: str,
                                agent_replicas: int) -> None:
    log.info("Deploying %d konnectivity-agents in %s on dataplane...", agent_replicas, namespace)
    manifest = render_template(MANIFEST_DIR / "konnectivity-agent.yaml", {
        "__NAMESPACE__": namespace,
        "__AGENT_IMAGE__": KONN_AGENT_IMAGE,
        "__SERVER_HOST__": server_host,
        "__SERVER_PORT__": "8081",
        "__AGENT_REPLICAS__": str(agent_replicas),
    })
    kubectl_apply(kubeconfig, manifest)
    kubectl(kubeconfig, "-n", namespace, "rollout", "status",
            "deployment/konnectivity-agent", "--timeout=300s")
    log.info("Konnectivity agents ready in %s", namespace)


@retry(max_attempts=3, backoff=10.0)
def deploy_fake_exporters(kubeconfig: str, replicas: int, profile: str = "default") -> None:
    total = replicas * len(FAKE_EXPORTER_ROLES)
    log.info("Deploying fake exporters: %d replicas × %d roles = %d targets (profile=%s)...",
             replicas, len(FAKE_EXPORTER_ROLES), total, profile)
    manifest = render_template(FAKE_EXPORTER_DIR / "scrape-targets.yaml", {
        "__REPLICAS__": str(replicas),
        "__EXPORTER_IMAGE__": FAKE_EXPORTER_IMAGE,
        "__PROFILE__": profile,
    })
    kubectl_apply(kubeconfig, manifest)
    for sts_name, _, _ in FAKE_EXPORTER_ROLES:
        kubectl(kubeconfig, "-n", FAKE_EXPORTER_NS, "rollout", "status",
                f"statefulset/{sts_name}", "--timeout=600s")
    log.info("Fake exporters ready: %d total pods", total)


def get_dp_api_server(dp_kubeconfig: str) -> str:
    """Extract the API server URL from a kubeconfig file."""
    with open(dp_kubeconfig) as f:
        kc = yaml.safe_load(f)
    return kc["clusters"][0]["cluster"]["server"]


def get_node_ips(kubeconfig: str) -> list[str]:
    result = kubectl(
        kubeconfig, "get", "nodes",
        "-o", "jsonpath={range .items[*]}{.status.addresses[?(@.type==\"InternalIP\")].address}{\"\\n\"}{end}",
    )
    return [ip.strip() for ip in result.stdout.strip().split("\n") if ip.strip()]


def setup_dp_access(dp_kubeconfig: str, cp_kubeconfig: str, namespace: str) -> None:
    """Create SA + RBAC on DP for kubernetes_sd_configs and kubelet scraping, transfer token to CP."""
    log.info("Setting up DP access (SD + kubelet RBAC)...")

    sa_yaml = f"""apiVersion: v1
kind: ServiceAccount
metadata:
  name: {KUBELET_SA_NAME}
  namespace: {namespace}
"""
    kubectl_apply(dp_kubeconfig, sa_yaml)

    # kubelet-api-admin: nodes/proxy, nodes/metrics, etc.
    crb_yaml = f"""apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {KUBELET_SA_NAME}-kubelet
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:kubelet-api-admin
subjects:
  - kind: ServiceAccount
    name: {KUBELET_SA_NAME}
    namespace: {namespace}
"""
    kubectl_apply(dp_kubeconfig, crb_yaml)

    # view: pods/nodes/endpoints list/watch (needed for kubernetes_sd_configs)
    view_crb_yaml = f"""apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {KUBELET_SA_NAME}-view
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: view
subjects:
  - kind: ServiceAccount
    name: {KUBELET_SA_NAME}
    namespace: {namespace}
"""
    kubectl_apply(dp_kubeconfig, view_crb_yaml)

    result = kubectl(
        dp_kubeconfig, "-n", namespace,
        "create", "token", KUBELET_SA_NAME, "--duration=2h",
    )
    token = result.stdout.strip()

    secret_cmd = [
        "kubectl", "--kubeconfig", cp_kubeconfig, "-n", namespace,
        "create", "secret", "generic", "kubelet-scrape-token",
        f"--from-literal=token={token}",
        "--dry-run=client", "-o", "yaml",
    ]
    result = run(secret_cmd)
    run(["kubectl", "--kubeconfig", cp_kubeconfig, "apply", "-f", "-"],
        input=result.stdout, capture=False)
    log.info("DP access token transferred to CP namespace %s", namespace)


def deploy_vmsingle(kubeconfig: str, namespace: str) -> None:
    log.info("Deploying vmsingle receiver in %s...", namespace)
    manifest = render_template(MANIFEST_DIR / "vmsingle.yaml", {
        "__NAMESPACE__": namespace,
    })
    kubectl_apply(kubeconfig, manifest)
    kubectl(kubeconfig, "-n", namespace, "rollout", "status",
            "deployment/vmsingle", "--timeout=180s")
    log.info("vmsingle ready in %s", namespace)


def deploy_vmagent(kubeconfig: str, namespace: str, dp_api_server: str) -> None:
    log.info("Deploying VMAgent in %s (SD via %s)...", namespace, dp_api_server)
    replacements = {
        "__NAMESPACE__": namespace,
        "__VMAGENT_IMAGE__": VMAGENT_IMAGE,
        "__DP_API_SERVER__": dp_api_server,
    }
    manifest = render_template(MANIFEST_DIR / "vmagent.yaml", replacements)
    kubectl_apply(kubeconfig, manifest)
    kubectl(kubeconfig, "-n", namespace, "rollout", "status",
            "statefulset/vmagent", "--timeout=180s")
    log.info("VMAgent ready in %s", namespace)


def rollout_restart(kubeconfig: str, namespace: str, resource: str) -> None:
    kubectl(kubeconfig, "-n", namespace, "rollout", "restart", resource)
    kubectl(kubeconfig, "-n", namespace, "rollout", "status", resource, "--timeout=300s")
