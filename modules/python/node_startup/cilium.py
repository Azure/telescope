"""Cilium agent Prometheus metrics: port discovery, scrape, and parsing (ported from v1)."""
import re

from utils.logger_config import get_logger

logger = get_logger(__name__)

DEFAULT_METRICS_PORT = 9962
MIN_METRICS_BYTES = 100


def scrape_cilium_metrics(k8s, node_name, cni_daemonset_label, namespace="kube-system",
                          metrics_port=DEFAULT_METRICS_PORT):
    """Fetch and parse the Cilium agent's metrics on `node_name`; None if scraping fails.

    Tries the API server pod proxy first (no tools needed in the image), then
    falls back to exec with wget/curl.
    """
    pods = k8s.get_pods_by_namespace(
        namespace=namespace,
        label_selector=cni_daemonset_label,
        field_selector=f"spec.nodeName={node_name}",
    )
    if not pods:
        logger.warning("Deep Cilium: no agent pod on node '%s'", node_name)
        return None

    agent_pod = pods[0]
    agent_pod_name = agent_pod.metadata.name

    container_name = "cilium-agent"
    if agent_pod.spec.containers:
        for container in agent_pod.spec.containers:
            if "cilium" in container.name and "monitor" not in container.name:
                container_name = container.name
                break

    port = detect_cilium_metrics_port(k8s, agent_pod, agent_pod_name, container_name, namespace, metrics_port)
    logger.info("Deep Cilium: fetching metrics from pod '%s' port %d", agent_pod_name, port)

    try:
        output = k8s.api.connect_get_namespaced_pod_proxy_with_path(
            name=f"{agent_pod_name}:{port}",
            namespace=namespace,
            path="metrics",
        )
        if output and len(output) >= MIN_METRICS_BYTES:
            logger.info("Deep Cilium: got %d bytes via API proxy", len(output))
            return parse_cilium_metrics(output)
        logger.warning("Deep Cilium: API proxy returned too little data (%d bytes)",
                       len(output) if output else 0)
    except Exception as e:
        logger.warning("Deep Cilium: API proxy failed on '%s:%d': %s", agent_pod_name, port, e)

    logger.info("Deep Cilium: falling back to exec scrape on '%s'", agent_pod_name)
    try:
        metrics_url = f"http://localhost:{port}/metrics"
        command = (
            f"wget -q -O - --timeout=10 {metrics_url} 2>/dev/null "
            f"|| curl -s --max-time 10 {metrics_url} 2>/dev/null"
        )
        output = k8s.run_pod_exec_command(
            pod_name=agent_pod_name,
            command=command,
            container_name=container_name,
            namespace=namespace,
        )
        if not output or len(output) < MIN_METRICS_BYTES:
            logger.warning("Deep Cilium: exec fallback also failed (%d bytes)", len(output) if output else 0)
            return None
        logger.info("Deep Cilium: got %d bytes via exec fallback", len(output))
        return parse_cilium_metrics(output)
    except Exception as e:
        logger.warning("Deep Cilium: exec fallback failed on '%s': %s", agent_pod_name, e)
        return None


def detect_cilium_metrics_port(k8s, agent_pod, pod_name, container_name, namespace, default_port):
    """Find the agent's metrics port: container spec, then runtime config (AKS may differ from upstream)."""
    if agent_pod.spec.containers:
        for container in agent_pod.spec.containers:
            if container.name == container_name and container.ports:
                for port in container.ports:
                    if port.name in ("prometheus", "metrics", "prometheus-metrics"):
                        logger.info("Deep Cilium: detected port %d from container spec (name=%s)",
                                    port.container_port, port.name)
                        return port.container_port

    try:
        discover_command = (
            "cat /tmp/cilium/config-map/prometheus-serve-addr 2>/dev/null"
            " || cat /var/run/cilium/state/agent-runtime-config.json 2>/dev/null"
            " | grep -o 'prometheus-serve-addr[^,]*' 2>/dev/null"
            " || grep -r 'prometheus' /tmp/cilium/config-map/ 2>/dev/null"
            " || echo DISCOVERY_FAILED"
        )
        output = k8s.run_pod_exec_command(
            pod_name=pod_name,
            command=discover_command,
            container_name=container_name,
            namespace=namespace,
        )
        if output and "DISCOVERY_FAILED" not in output:
            # Address looks like ":9962" or "0.0.0.0:9090".
            port_match = re.search(r':(\d+)', output.strip())
            if port_match:
                discovered = int(port_match.group(1))
                logger.info("Deep Cilium: discovered port %d from runtime config: %s",
                            discovered, output.strip()[:80])
                return discovered
        logger.info("Deep Cilium: port discovery output: %s", output.strip()[:120] if output else "(empty)")
    except Exception as e:
        logger.info("Deep Cilium: port discovery exec failed: %s", e)

    logger.info("Deep Cilium: using default port %d", default_port)
    return default_port


def parse_cilium_metrics(metrics_text):
    """Extract bootstrap phases, mean endpoint regeneration per scope, and agent metadata."""
    result = {
        "bootstrap": {},
        "endpoint_regen": {},
        "metadata": {
            "cilium_identity_count": None,
            "cilium_bpf_map_pressure": None,
            "cilium_version": None,
        },
    }
    # Cilium 1.14+ reports identities as per-type gauges that have to be summed.
    identity_gauge_total = 0
    identity_gauge_found = False

    for line in metrics_text.splitlines():
        if line.startswith("#"):
            continue

        if line.startswith("cilium_bootstrap_seconds{") or line.startswith("cilium_agent_bootstrap_seconds{"):
            try:
                scope = line.split('scope="')[1].split('"')[0]
                result["bootstrap"][scope] = float(line.split("} ")[1])
            except (IndexError, ValueError):
                continue
        elif line.startswith("cilium_endpoint_regeneration_time_stats_seconds_sum{"):
            try:
                scope = line.split('scope="')[1].split('"')[0]
                result["endpoint_regen"].setdefault(scope, {})["sum"] = float(line.split("} ")[1])
            except (IndexError, ValueError):
                continue
        elif line.startswith("cilium_endpoint_regeneration_time_stats_seconds_count{"):
            try:
                scope = line.split('scope="')[1].split('"')[0]
                result["endpoint_regen"].setdefault(scope, {})["count"] = float(line.split("} ")[1])
            except (IndexError, ValueError):
                continue
        elif line.startswith("cilium_version_info{"):
            try:
                if 'version="' in line:
                    result["metadata"]["cilium_version"] = line.split('version="')[1].split('"')[0]
            except (IndexError, ValueError):
                pass
        elif line.startswith("cilium_identity_count "):
            try:
                result["metadata"]["cilium_identity_count"] = int(float(line.split(" ")[1]))
            except (IndexError, ValueError):
                pass
        elif line.startswith("cilium_identity{"):
            try:
                identity_gauge_total += int(float(line.split("} ")[1]))
                identity_gauge_found = True
            except (IndexError, ValueError):
                pass
        elif line.startswith("cilium_bpf_map_pressure{"):
            try:
                value = float(line.split("} ")[1])
                current = result["metadata"]["cilium_bpf_map_pressure"]
                if current is None or value > current:
                    result["metadata"]["cilium_bpf_map_pressure"] = value
            except (IndexError, ValueError):
                pass

    if result["metadata"]["cilium_identity_count"] is None and identity_gauge_found:
        result["metadata"]["cilium_identity_count"] = identity_gauge_total

    regen_means = {}
    for scope, values in result["endpoint_regen"].items():
        total = values.get("sum", 0)
        count = values.get("count", 0)
        regen_means[scope] = total / count if count > 0 else 0
    result["endpoint_regen"] = regen_means
    return result
