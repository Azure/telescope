"""Deployment helpers for all load test components."""

import json
import time
from pathlib import Path

import yaml

from .config import (
    AGENT_NODE_LABEL_KEY, AGENT_NODE_LABEL_VALUE, AGENT_TAINT_EFFECT,
    AGENT_TAINT_KEY, AGENT_TAINT_VALUE,
    FAKE_EXPORTER_DIR, FAKE_EXPORTER_IMAGE, FAKE_EXPORTER_NS,
    FAKE_EXPORTER_ROLES, KONN_AGENT_AUTOSCALER_IMAGE, KONN_AGENT_IMAGE, KONN_SERVER_IMAGE,
    KUBELET_SA_NAME, MANIFEST_DIR, NODE_AGGREGATOR_IMAGE, VMAGENT_IMAGE, VMAGENT_PROXY_IMAGE,
    VMSINGLE_IMAGE,
    VMAGENT_RATE_LIMIT, VMAGENT_FLUSH_INTERVAL,
    log,
)
from .utils import kubectl, kubectl_apply, render_template, retry, run

from urllib.parse import urlparse


def _force_clear_namespace(kubeconfig: str, namespace: str) -> None:
    """Best-effort: force-delete and strip finalizers from a stuck namespace."""
    kubectl(kubeconfig, "delete", "ns", namespace, "--grace-period=0", "--force", check=False)
    result = kubectl(kubeconfig, "get", "ns", namespace, "-o", "json", check=False)
    if result.returncode != 0:
        return
    ns_obj = json.loads(result.stdout)
    ns_obj.setdefault("spec", {})["finalizers"] = []
    run(["kubectl", "--kubeconfig", kubeconfig, "replace", "--raw",
         f"/api/v1/namespaces/{namespace}/finalize", "-f", "-"],
        input=json.dumps(ns_obj), capture=False, check=False)


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
    else:
        # Still Terminating after 5m of normal waiting -- a stuck finalizer,
        # not just slow cleanup. Force-clear now instead of proceeding to
        # apply (guaranteed Forbidden) and burning ~70min across 3 outer
        # ramp retries (seen in build 77430).
        log.warning("  Namespace %s still Terminating after 5m — forcing finalizer clear", namespace)
        _force_clear_namespace(kubeconfig, namespace)
        for _ in range(12):
            result = kubectl(kubeconfig, "get", "ns", namespace, "-o", "jsonpath={.status.phase}", check=False)
            if result.returncode != 0:
                break
            time.sleep(5)
        else:
            raise RuntimeError(
                f"Namespace {namespace} still stuck Terminating after forced finalizer "
                "clear — needs manual cluster investigation (stuck resource finalizer)."
            )
    result = run(
        ["kubectl", "--kubeconfig", kubeconfig, "create", "ns", namespace,
         "--dry-run=client", "-o", "yaml"]
    )
    run(["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"],
        input=result.stdout, capture=False)
    kubectl(kubeconfig, "label", "ns", namespace, "loadtest=true", "--overwrite", check=False)


@retry(max_attempts=3, backoff=5.0)
def deploy_konnectivity_server(kubeconfig: str, namespace: str, server_count: int = 1,
                                resources: dict | None = None,
                                wait: bool = True,
                                server_image: str = KONN_SERVER_IMAGE) -> None:
    log.info("Deploying konnectivity-server in %s on control plane...", namespace)
    r = resources or {"cpu_req": "500m", "mem_req": "512Mi",
                      "cpu_lim": "2", "mem_lim": "2Gi"}
    manifest = render_template(MANIFEST_DIR / "konnectivity-server.yaml", {
        "__NAMESPACE__": namespace,
        "__SERVER_IMAGE__": server_image,
        "__SERVER_COUNT__": str(server_count),
        "__SERVER_CPU_REQ__": r["cpu_req"],
        "__SERVER_MEM_REQ__": r["mem_req"],
        "__SERVER_CPU_LIM__": r["cpu_lim"],
        "__SERVER_MEM_LIM__": r["mem_lim"],
    })
    kubectl_apply(kubeconfig, manifest)
    if wait:
        kubectl(kubeconfig, "-n", namespace, "rollout", "status",
                "deployment/konnectivity-server", "--timeout=300s")
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
                                agent_replicas: int,
                                agent_image: str = KONN_AGENT_IMAGE,
                                dedicated_pool: bool = False) -> None:
    log.info("Deploying %d konnectivity-agents in %s on dataplane%s...",
             agent_replicas, namespace, " (dedicated nodepool)" if dedicated_pool else "")
    node_affinity = ""
    if dedicated_pool:
        node_affinity = (
            f"      nodeSelector:\n"
            f"        {AGENT_NODE_LABEL_KEY}: {AGENT_NODE_LABEL_VALUE}\n"
            f"      tolerations:\n"
            f"        - key: {AGENT_TAINT_KEY}\n"
            f"          operator: Equal\n"
            f"          value: {AGENT_TAINT_VALUE}\n"
            f"          effect: {AGENT_TAINT_EFFECT}"
        )
    manifest = render_template(MANIFEST_DIR / "konnectivity-agent.yaml", {
        "__NAMESPACE__": namespace,
        "__AGENT_IMAGE__": agent_image,
        "__SERVER_HOST__": server_host,
        "__SERVER_PORT__": "8081",
        "__AGENT_REPLICAS__": str(agent_replicas),
        "__AGENT_NODE_AFFINITY__": node_affinity,
    })
    kubectl_apply(kubeconfig, manifest)
    kubectl(kubeconfig, "-n", namespace, "rollout", "status",
            "deployment/konnectivity-agent", "--timeout=600s")
    log.info("Konnectivity agents ready in %s", namespace)


def deploy_konnectivity_agent_autoscaler(kubeconfig: str, namespace: str, min_replicas: int) -> None:
    """Deploy the real konnectivity-agent-autoscaler to scale konnectivity-agent
    off live agent packet metrics + a replica floor, instead of a Python-computed
    static --replicas.
    """
    log.info("Deploying konnectivity-agent-autoscaler in %s (min_replicas=%d)...",
             namespace, min_replicas)
    manifest = render_template(MANIFEST_DIR / "konnectivity-agent-autoscaler.yaml", {
        "__NAMESPACE__": namespace,
        "__AUTOSCALER_IMAGE__": KONN_AGENT_AUTOSCALER_IMAGE,
        "__MIN_REPLICAS__": str(min_replicas),
    })
    kubectl_apply(kubeconfig, manifest)
    kubectl(kubeconfig, "-n", namespace, "rollout", "status",
            "deployment/konnectivity-agent-autoscaler", "--timeout=300s")
    log.info("Konnectivity-agent-autoscaler ready in %s", namespace)


def update_konn_agent_autoscaler_floor(kubeconfig: str, namespace: str, min_replicas: int) -> None:
    """Update the replica floor for a running autoscaler and restart it to pick
    up the change -- its ConfigMap is only read once at startup.
    """
    log.info("Updating konnectivity-agent-autoscaler min_replicas=%d in %s...",
             min_replicas, namespace)
    manifest = render_template(MANIFEST_DIR / "konnectivity-agent-autoscaler.yaml", {
        "__NAMESPACE__": namespace,
        "__AUTOSCALER_IMAGE__": KONN_AGENT_AUTOSCALER_IMAGE,
        "__MIN_REPLICAS__": str(min_replicas),
    })
    kubectl_apply(kubeconfig, manifest)
    rollout_restart(kubeconfig, namespace, "deployment/konnectivity-agent-autoscaler")


def deploy_node_aggregator(dp_kubeconfig: str, namespace: str) -> None:
    """Deploy the real per-node Prometheus aggregator DaemonSet (prototype).

    Scrapes kubelet/cadvisor/kube-proxy/azure-cns/node-exporter/node-runtime
    locally on each DP node and exposes them combined via /federate, so
    central vmagent can scrape one target per node instead of six.
    """
    log.info("Deploying node-aggregator DaemonSet in %s...", namespace)
    manifest = render_template(MANIFEST_DIR / "node-aggregator.yaml", {
        "__NAMESPACE__": namespace,
        "__NODE_AGGREGATOR_IMAGE__": NODE_AGGREGATOR_IMAGE,
    })
    kubectl_apply(dp_kubeconfig, manifest)
    kubectl(dp_kubeconfig, "-n", namespace, "rollout", "status",
            "daemonset/node-aggregator", "--timeout=300s")
    log.info("node-aggregator ready in %s", namespace)


def _wait_statefulsets_ready(kubeconfig: str, namespace: str,
                              statefulsets: list[tuple[str, str, str]],
                              timeout: int = 600, interval: int = 10) -> None:
    """Wait for multiple StatefulSets in parallel with progress logging and image-pull checks."""
    deadline = time.time() + timeout

    while True:
        all_ready = True
        status_parts = []

        for sts_name, app_label, _ in statefulsets:
            # Image-pull check: scan pods for fatal pull errors
            pod_result = kubectl(kubeconfig, "-n", namespace, "get", "pods",
                                 "-l", f"app={app_label}", "-o", "json", check=False)
            if pod_result.returncode == 0:
                pods = json.loads(pod_result.stdout)
                for pod in pods.get("items", []):
                    for cs in pod.get("status", {}).get("containerStatuses", []):
                        waiting = cs.get("state", {}).get("waiting", {})
                        reason = waiting.get("reason", "")
                        if reason in ("ImagePullBackOff", "ErrImagePull"):
                            raise RuntimeError(
                                f"Image pull failed for {pod['metadata']['name']}: "
                                f"{waiting.get('message', reason)}")

            # Rollout progress
            result = kubectl(kubeconfig, "-n", namespace, "get", f"statefulset/{sts_name}",
                             "-o", "jsonpath={.status.readyReplicas},{.spec.replicas}",
                             check=False)
            if result.returncode != 0:
                status_parts.append(f"{sts_name}: 0/?")
                all_ready = False
                continue

            parts = result.stdout.strip().split(",")
            ready = int(parts[0]) if parts[0] else 0
            desired = int(parts[1]) if len(parts) > 1 and parts[1] else 0
            status_parts.append(f"{sts_name}: {ready}/{desired}")
            if ready < desired:
                all_ready = False

        log.info("  Rollout progress: %s", " | ".join(status_parts))

        if all_ready:
            return

        if time.time() > deadline:
            raise RuntimeError(
                f"Timed out waiting for StatefulSets in {namespace}: "
                + " | ".join(status_parts))

        time.sleep(interval)


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
    _wait_statefulsets_ready(kubeconfig, FAKE_EXPORTER_NS, FAKE_EXPORTER_ROLES)
    log.info("Fake exporters ready: %d total pods", total)


def scale_fake_exporters(kubeconfig: str, replicas: int) -> None:
    """Scale all fake-exporter StatefulSets to `replicas`.

    Used to pause (replicas=0) scrape-target generation before a genuine
    remote-write drain-time measurement, and to resume (replicas=<tier>)
    afterward. Pausing mirrors what happens on SIGTERM in real vmagent: its
    promscrape scrape loops are canceled and only the remote-write drain
    continues, so measuring drain rate while targets are still being
    actively scraped conflates "can drain keep up with arrivals" with
    "how fast does the existing backlog actually drain" -- two different
    questions. Best-effort: failures are logged, not raised, since this is
    a diagnostic aid and shouldn't fail the whole tier run.
    """
    log.info("Scaling fake exporters to %d replicas...", replicas)
    for sts_name, _app, _port in FAKE_EXPORTER_ROLES:
        result = kubectl(kubeconfig, "-n", FAKE_EXPORTER_NS, "scale",
                         f"statefulset/{sts_name}", f"--replicas={replicas}",
                         check=False)
        if result.returncode != 0:
            log.warning("Failed to scale %s to %d replicas: %s",
                       sts_name, replicas, result.stderr.strip())


def wait_for_fake_exporters_gone(kubeconfig: str, timeout_seconds: int = 90) -> bool:
    """Wait until no fake-exporter pods remain (after scale_fake_exporters(0)).

    Returns True if all pods terminated within the timeout, False otherwise
    (caller should proceed anyway -- this is best-effort synchronization,
    not a hard requirement).
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = kubectl(kubeconfig, "-n", FAKE_EXPORTER_NS, "get", "pods",
                         "-o", "jsonpath={.items[*].metadata.name}", check=False)
        remaining = result.stdout.strip() if result.returncode == 0 else ""
        if not remaining:
            log.info("All fake-exporter pods terminated.")
            return True
        time.sleep(5)
    log.warning("Timed out waiting for fake-exporter pods to terminate after %ds", timeout_seconds)
    return False


def get_dp_api_server(dp_kubeconfig: str) -> str:
    """Extract the API server URL from a kubeconfig file."""
    with open(dp_kubeconfig) as f:
        kc = yaml.safe_load(f)
    return kc["clusters"][0]["cluster"]["server"]


def get_deployment_replicas(kubeconfig: str, namespace: str, deployment: str) -> int:
    """Live replica count -- used to report what the autoscaler actually set,
    not just the floor we configured it with.
    """
    result = kubectl(kubeconfig, "-n", namespace, "get", f"deployment/{deployment}",
                     "-o", "jsonpath={.spec.replicas}", check=False)
    return int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else 0


def get_node_ips(kubeconfig: str, label_selector: str = "") -> list[str]:
    args = ["get", "nodes", "-o",
            "jsonpath={range .items[*]}{.status.addresses[?(@.type==\"InternalIP\")].address}{\"\\n\"}{end}"]
    if label_selector:
        args += ["-l", label_selector]
    result = kubectl(kubeconfig, *args)
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
        "__VMSINGLE_IMAGE__": VMSINGLE_IMAGE,
    })
    kubectl_apply(kubeconfig, manifest)
    kubectl(kubeconfig, "-n", namespace, "rollout", "status",
            "deployment/vmsingle", "--timeout=300s")
    log.info("vmsingle ready in %s", namespace)


# Default: 6 direct per-node-per-role jobs, each scraping through
# konnectivity (kubelet/cadvisor) or the vmagent-proxy sidecar (the rest).
_REAL_TARGET_JOBS_DIRECT = """\
      - job_name: real-kubelet
        stream_parse: true
        proxy_url: "https://konnectivity-server:8083"
        proxy_tls_config:
          insecure_skip_verify: true
          ca_file: /certs/ca.crt
          cert_file: /certs/client.crt
          key_file: /certs/client.key
        scheme: https
        metrics_path: /metrics
        authorization:
          type: Bearer
          credentials_file: /var/run/secrets/kubelet/token
        tls_config:
          insecure_skip_verify: true
        kubernetes_sd_configs:
          - role: node
            api_server: "__DP_API_SERVER__"
            bearer_token_file: /var/run/secrets/kubelet/token
            tls_config:
              insecure_skip_verify: true
        relabel_configs:
          - source_labels: [__meta_kubernetes_node_label_loadtest_io_tier_block]
            regex: '__TIER_BLOCK_REGEX__'
            action: keep
          - source_labels: [__meta_kubernetes_node_address_InternalIP]
            target_label: __address__
            replacement: $1:10250
          - source_labels: [__address__]
            target_label: instance

      - job_name: real-cadvisor
        stream_parse: true
        proxy_url: "https://konnectivity-server:8083"
        proxy_tls_config:
          insecure_skip_verify: true
          ca_file: /certs/ca.crt
          cert_file: /certs/client.crt
          key_file: /certs/client.key
        scheme: https
        metrics_path: /metrics/cadvisor
        authorization:
          type: Bearer
          credentials_file: /var/run/secrets/kubelet/token
        tls_config:
          insecure_skip_verify: true
        kubernetes_sd_configs:
          - role: node
            api_server: "__DP_API_SERVER__"
            bearer_token_file: /var/run/secrets/kubelet/token
            tls_config:
              insecure_skip_verify: true
        relabel_configs:
          - source_labels: [__meta_kubernetes_node_label_loadtest_io_tier_block]
            regex: '__TIER_BLOCK_REGEX__'
            action: keep
          - source_labels: [__meta_kubernetes_node_address_InternalIP]
            target_label: __address__
            replacement: $1:10250
          - source_labels: [__address__]
            target_label: instance
        # Mirrors prod's cadvisor metric_relabel_configs verbatim (aks-operator
        # config/channels/packages/adx-vmagent/full-mode/scale_scrape_configs.yaml)
        # -- cadvisor emits thousands of per-container metrics; prod only keeps
        # a curated metric-name allowlist for containers/pods matching known
        # system workloads.
        metric_relabel_configs:
          - action: keep
            if: '{__name__=~"container_cpu_cfs_throttled_seconds_total|container_cpu_cfs_throttled_periods_total|container_cpu_cfs_periods_total|container_cpu_load_average_10s|container_cpu_system_seconds_total|container_cpu_usage_seconds_total|container_cpu_user_seconds_total|container_memory_cache|container_memory_failcnt|container_memory_failures_total|container_memory_mapped_file|container_memory_rss|container_memory_swap|container_memory_usage_bytes|container_memory_working_set_bytes|container_oom_events_total|container_spec_memory_limit_bytes|container_spec_memory_reservation_limit_bytes|container_spec_memory_swap_limit_bytes|container_network_transmit_errors_total|container_network_receive_errors_total|container_network_transmit_packets_dropped_total|container_network_receive_packets_dropped_total|container_network_receive_packets_total|container_network_transmit_packets_total|container_fs_reads_bytes_total|container_fs_writes_bytes_total|container_scrape_error|container_tasks_state|go_memstats_heap_alloc_bytes|go_memstats_heap_idle_bytes|go_memstats_heap_inuse_bytes|go_memstats_heap_objects|go_memstats_alloc_bytes_total|go_gc_duration_seconds($|_count|_sum)|go_gc_pauses_seconds_(bucket|count|sum)|go_gc_cycles_automatic_gc_cycles_total|go_goroutines|go_threads|process_open_fds|process_cpu_seconds_total"}'
          - action: keep
            if: '{namespace=~"(aks-istio-ingress|aks-istio-system|app-routing-system|applink-system|eno-system|gatekeeper-system|kube-system|tigera-operator|^$)"}'
          - target_label: cadvisor_keep_label
            replacement: keep_metric
            if: '{container=~"(alb-controller|app-monitoring-webhook|keda-admission-webhooks|keda-operator|keda-operator-metrics-apiserver|konnectivity-agent|updater|recommender|admission-controller|cilium-agent|istio-proxy|cilium-envoy|fqdn-policy|kube-proxy|retina|cns-container|blob|azuredisk|azurefile|coredns|gatekeeper-controller-container|workspace|kaito_workload|eviction-autoscaler|discovery|daemon|cluster-health-monitor)"}'
          - target_label: cadvisor_keep_label
            replacement: keep_metric
            if: '{pod=~"(alb-controller.*|app-monitoring-webhook.*|keda-admission-webhooks.*|keda-operator.*|keda-operator-metrics-apiserver.*|konnectivity-agent.*|vpa-updater.*|vpa-recommender.*|vpa-admission-controller.*|cilium-agent.*|ztunnel.*|acns-security-agent.*|acns-security-agent.*|kube-proxy.*|retina_basic.*|azure-cns.*|blob.*|csi-azuredisk-node.*|csi-azurefile-node.*|coredns.*|gatekeeper-controller.*|kaito-workspace.*|kaito_workload.*|eviction-autoscaler.*|istiod.*|kube-egress-gateway-daemon-manager.*|cluster-health-monitor.*)"}'
          - source_labels: [cadvisor_keep_label]
            action: keep
            regex: (.*)
          - action: labeldrop
            regex: cadvisor_keep_label
          - action: labeldrop
            regex: id|image

      - job_name: real-kubeproxy
        stream_parse: true
        proxy_url: "http://localhost:8080"
        metrics_path: /metrics
        kubernetes_sd_configs:
          - role: node
            api_server: "__DP_API_SERVER__"
            bearer_token_file: /var/run/secrets/kubelet/token
            tls_config:
              insecure_skip_verify: true
        relabel_configs:
          - source_labels: [__meta_kubernetes_node_label_loadtest_io_tier_block]
            regex: '__TIER_BLOCK_REGEX__'
            action: keep
          - source_labels: [__meta_kubernetes_node_address_InternalIP]
            target_label: __address__
            replacement: $1:10249
          - source_labels: [__address__]
            target_label: instance

      - job_name: real-azure-cns
        stream_parse: true
        proxy_url: "http://localhost:8080"
        metrics_path: /metrics
        kubernetes_sd_configs:
          - role: node
            api_server: "__DP_API_SERVER__"
            bearer_token_file: /var/run/secrets/kubelet/token
            tls_config:
              insecure_skip_verify: true
        relabel_configs:
          - source_labels: [__meta_kubernetes_node_label_loadtest_io_tier_block]
            regex: '__TIER_BLOCK_REGEX__'
            action: keep
          - source_labels: [__meta_kubernetes_node_address_InternalIP]
            target_label: __address__
            replacement: $1:10092
          - source_labels: [__address__]
            target_label: instance

      - job_name: node-exporter
        stream_parse: true
        proxy_url: "http://localhost:8080"
        metrics_path: /metrics
        kubernetes_sd_configs:
          - role: node
            api_server: "__DP_API_SERVER__"
            bearer_token_file: /var/run/secrets/kubelet/token
            tls_config:
              insecure_skip_verify: true
        relabel_configs:
          - source_labels: [__meta_kubernetes_node_label_loadtest_io_tier_block]
            regex: '__TIER_BLOCK_REGEX__'
            action: keep
          - source_labels: [__meta_kubernetes_node_label_kubernetes_io_os]
            action: keep
            regex: linux
          - source_labels: [__meta_kubernetes_node_address_InternalIP]
            target_label: __address__
            replacement: $1:19100
          - source_labels: [__address__]
            target_label: instance

      - job_name: node-runtime
        stream_parse: true
        proxy_url: "http://localhost:8080"
        metrics_path: /v1/metrics
        kubernetes_sd_configs:
          - role: node
            api_server: "__DP_API_SERVER__"
            bearer_token_file: /var/run/secrets/kubelet/token
            tls_config:
              insecure_skip_verify: true
        relabel_configs:
          - source_labels: [__meta_kubernetes_node_label_loadtest_io_tier_block]
            regex: '__TIER_BLOCK_REGEX__'
            action: keep
          - source_labels: [__meta_kubernetes_node_address_InternalIP]
            target_label: __address__
            replacement: $1:10257
          - source_labels: [__address__]
            target_label: instance"""

# Prototype: 1 job per node, scraping the node-aggregator DaemonSet's real
# Prometheus /federate instead of 6 direct scrapes. attach_metadata.node
# recovers the tier-block label (role:pod SD has no node labels otherwise).
_REAL_TARGET_JOBS_AGGREGATOR = """\
      - job_name: real-node-aggregator
        stream_parse: true
        scrape_timeout: 25s
        proxy_url: "http://localhost:8080"
        metrics_path: /federate
        params:
          # Two selectors (federate matches the union of all match[]
          # values): the 6 real targets in full, plus ONLY the 3 specific
          # self-metrics adx.py's resource-peak queries need from the
          # node-aggregator's own self-scrape (job="prometheus") -- not
          # that job's full ~800 internal engine metrics, which used to
          # get swept in by a bare '{__name__!=""}' selector and roughly
          # doubled ingested row count vs direct mode for the same 6 real
          # targets (an apples-vs-oranges cardinality mismatch, not a
          # genuine aggregator overhead).
          'match[]':
            - '{job!="prometheus"}'
            - '{job="prometheus",__name__=~"process_resident_memory_bytes|process_cpu_seconds_total|go_goroutines"}'
        honor_labels: true
        kubernetes_sd_configs:
          - role: pod
            api_server: "__DP_API_SERVER__"
            bearer_token_file: /var/run/secrets/kubelet/token
            tls_config:
              insecure_skip_verify: true
            attach_metadata:
              node: true
            namespaces:
              names: ["__NAMESPACE__"]
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_label_app]
            regex: node-aggregator
            action: keep
          - source_labels: [__meta_kubernetes_node_label_loadtest_io_tier_block]
            regex: '__TIER_BLOCK_REGEX__'
            action: keep
          - source_labels: [__meta_kubernetes_pod_ip]
            target_label: __address__
            replacement: $1:9090
          - source_labels: [__address__]
            target_label: instance"""


def _scrape_config_replacements(namespace: str, dp_api_server: str, tier_block_regex: str,
                                node_aggregator: bool) -> dict:
    # __REAL_TARGET_JOBS__ must be substituted FIRST: its own value (the
    # aggregator job block) contains literal __NAMESPACE__/__DP_API_SERVER__/
    # __TIER_BLOCK_REGEX__ tokens, and render_template does a single
    # ordered pass over this dict -- if those keys ran first, their turn
    # would already be over by the time this substitution inserts more of
    # the same tokens, leaving them unresolved in the rendered output.
    return {
        "__REAL_TARGET_JOBS__": _REAL_TARGET_JOBS_AGGREGATOR if node_aggregator else _REAL_TARGET_JOBS_DIRECT,
        "__NAMESPACE__": namespace,
        "__DP_API_SERVER__": dp_api_server,
        "__DP_API_SERVER_HOST__": urlparse(dp_api_server).netloc or dp_api_server,
        "__TIER_BLOCK_REGEX__": tier_block_regex,
    }


def deploy_vmagent(kubeconfig: str, namespace: str, dp_api_server: str,
                   vmagent_resources: dict | None = None,
                   proxy_resources: dict | None = None,
                   replicas: int = 1,
                   rate_limit: int = VMAGENT_RATE_LIMIT,
                   max_block_size: int = 8388608,
                   tier_block_regex: str = ".*",
                   node_aggregator: bool = False) -> None:
    log.info("Deploying VMAgent in %s (SD via %s, %d shard(s), rateLimit=%d, maxBlockSize=%d, "
             "flushInterval=%s, tierBlockRegex=%s, nodeAggregator=%s)...",
             namespace, dp_api_server, replicas, rate_limit, max_block_size,
             VMAGENT_FLUSH_INTERVAL, tier_block_regex, node_aggregator)
    vm = vmagent_resources or {"cpu_req": "500m", "mem_req": "1Gi",
                               "cpu_lim": "2", "mem_lim": "4Gi"}
    px = proxy_resources or {"cpu_req": "500m", "mem_req": "256Mi",
                             "cpu_lim": "4", "mem_lim": "1Gi"}
    scrape_replacements = _scrape_config_replacements(namespace, dp_api_server, tier_block_regex,
                                                       node_aggregator)
    scrape_manifest = render_template(MANIFEST_DIR / "scrape-config.yaml", scrape_replacements)
    kubectl_apply(kubeconfig, scrape_manifest)

    replacements = {
        "__NAMESPACE__": namespace,
        "__VMAGENT_IMAGE__": VMAGENT_IMAGE,
        "__VMAGENT_REPLICAS__": str(replicas),
        "__VMAGENT_CPU_REQ__": vm["cpu_req"],
        "__VMAGENT_MEM_REQ__": vm["mem_req"],
        "__VMAGENT_CPU_LIM__": vm["cpu_lim"],
        "__VMAGENT_MEM_LIM__": vm["mem_lim"],
        "__PROXY_CPU_REQ__": px["cpu_req"],
        "__PROXY_MEM_REQ__": px["mem_req"],
        "__PROXY_CPU_LIM__": px["cpu_lim"],
        "__PROXY_MEM_LIM__": px["mem_lim"],
        "__VMAGENT_PROXY_IMAGE__": VMAGENT_PROXY_IMAGE,
        "__VMAGENT_RATE_LIMIT__": str(rate_limit),
        "__VMAGENT_MAX_BLOCK_SIZE__": str(max_block_size),
    }
    manifest = render_template(MANIFEST_DIR / "vmagent.yaml", replacements)
    kubectl_apply(kubeconfig, manifest)
    kubectl(kubeconfig, "-n", namespace, "rollout", "status",
            "statefulset/vmagent", "--timeout=600s")
    log.info("VMAgent ready in %s (%d shard(s))", namespace, replicas)


def set_tier_block_regex(kubeconfig: str, namespace: str, dp_api_server: str,
                         tier_block_regex: str, node_aggregator: bool = False) -> None:
    """Re-apply just the scrape-config ConfigMap to switch tier-block scope --
    no vmagent restart, no node scaling.
    """
    scrape_replacements = _scrape_config_replacements(namespace, dp_api_server, tier_block_regex,
                                                       node_aggregator)
    scrape_manifest = render_template(MANIFEST_DIR / "scrape-config.yaml", scrape_replacements)
    kubectl_apply(kubeconfig, scrape_manifest)
    log.info("Tier-block regex set to %r in %s (vmagent picks it up within ~10s)",
             tier_block_regex, namespace)


def rollout_restart(kubeconfig: str, namespace: str, resource: str) -> None:
    kubectl(kubeconfig, "-n", namespace, "rollout", "restart", resource)
    kubectl(kubeconfig, "-n", namespace, "rollout", "status", resource, "--timeout=600s")
