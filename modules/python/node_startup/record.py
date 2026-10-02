"""Result record for one uploaded iteration (plan section 6).

The envelope (timestamp, run_id, run_url, pipeline) is added by the pipeline;
this module builds the `result` payload.
"""
SCHEMA_VERSION = "1"
TEST_NAME = "node-startup-latency"


def cluster_info(aks_cluster, node_pool_name):
    """Selected fields of `az aks show -o json`, plus the measured node pool's profile."""
    network = aks_cluster.get("networkProfile") or {}
    pool = next((profile for profile in aks_cluster.get("agentPoolProfiles") or []
                 if profile.get("name") == node_pool_name), None)
    return {
        "cloud": "azure",
        "region": aks_cluster.get("location"),
        "cluster_id": aks_cluster.get("resourceUid"),
        "k8s_version": aks_cluster.get("currentKubernetesVersion"),
        "sku_tier": (aks_cluster.get("sku") or {}).get("tier"),
        "network_plugin": network.get("networkPlugin"),
        "network_plugin_mode": network.get("networkPluginMode"),
        "network_dataplane": network.get("networkDataplane"),
        "network_policy": network.get("networkPolicy"),
        "node_pool": None if pool is None else {
            "name": pool.get("name"),
            "vm_size": pool.get("vmSize"),
            "os_disk_type": pool.get("osDiskType"),
            "os_sku": pool.get("osSku"),
            "node_image_version": pool.get("nodeImageVersion"),
            "min_count": pool.get("minCount"),
            "max_count": pool.get("maxCount"),
        },
    }


def operation_info(start_timestamp, end_timestamp, duration_seconds):
    """Same shape as v1 `Operation.to_dict()` minus metadata; only successful iterations are uploaded."""
    return {
        "name": "autoscale_latency",
        "cloud": "azure",
        "start_timestamp": start_timestamp,
        "end_timestamp": end_timestamp,
        "duration": duration_seconds,
        "unit": "seconds",
        "success": True,
        "error_message": None,
    }


def build_record(scenario, provisioner, iteration, total_iterations, valid_iterations,
                 operation, cluster, config, environment, measurement):
    return {
        "schema_version": SCHEMA_VERSION,
        "test": TEST_NAME,
        "scenario": scenario,
        "provisioner": provisioner,
        "iteration": iteration,
        "total_iterations": total_iterations,
        "valid_iterations": valid_iterations,
        "operation": operation,
        "cluster": cluster,
        "config": config,
        "environment": environment,
        "measurement": measurement,
    }
