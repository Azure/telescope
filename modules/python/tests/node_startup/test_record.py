"""Result record assembly (plan section 6)."""
import unittest

from node_startup import record

AKS_CLUSTER = {
    "location": "eastus2euap",
    "resourceUid": "6ab984df1647dc0001775fd2",
    "currentKubernetesVersion": "1.36.1",
    "sku": {"name": "Base", "tier": "Standard"},
    "networkProfile": {"networkPlugin": "azure", "networkPluginMode": "overlay",
                       "networkDataplane": "cilium", "networkPolicy": "cilium"},
    "agentPoolProfiles": [
        {"name": "default", "vmSize": "Standard_D8s_v3"},
        {"name": "userpool", "vmSize": "Standard_D8s_v3", "osDiskType": "Ephemeral", "osSku": "Ubuntu",
         "nodeImageVersion": "AKSUbuntu-2204gen2containerd-202609.15.0", "minCount": 1, "maxCount": 10},
    ],
}


class ClusterInfoTest(unittest.TestCase):
    def test_selected_fields(self):
        self.assertEqual(record.cluster_info(AKS_CLUSTER, "userpool"), {
            "cloud": "azure",
            "region": "eastus2euap",
            "cluster_id": "6ab984df1647dc0001775fd2",
            "k8s_version": "1.36.1",
            "sku_tier": "Standard",
            "network_plugin": "azure",
            "network_plugin_mode": "overlay",
            "network_dataplane": "cilium",
            "network_policy": "cilium",
            "node_pool": {
                "name": "userpool",
                "vm_size": "Standard_D8s_v3",
                "os_disk_type": "Ephemeral",
                "os_sku": "Ubuntu",
                "node_image_version": "AKSUbuntu-2204gen2containerd-202609.15.0",
                "min_count": 1,
                "max_count": 10,
            },
        })

    def test_pool_not_in_cluster(self):
        self.assertIsNone(record.cluster_info(AKS_CLUSTER, "node-startup-latency")["node_pool"])


class BuildRecordTest(unittest.TestCase):
    def test_shape(self):
        built = record.build_record(
            scenario="managed-cilium", provisioner="cluster-autoscaler", iteration=2, total_iterations=5,
            valid_iterations=4, operation={"name": "autoscale_latency"}, cluster={"cloud": "azure"},
            config={"probe_namespace": "node-startup-latency"}, environment={"defender_sensor_present": False},
            measurement={"node_name": "n"})
        self.assertEqual(built, {
            "schema_version": "1",
            "benchmark": "node-startup-latency",
            "scenario": "managed-cilium",
            "provisioner": "cluster-autoscaler",
            "iteration": 2,
            "total_iterations": 5,
            "valid_iterations": 4,
            "operation": {"name": "autoscale_latency"},
            "cluster": {"cloud": "azure"},
            "config": {"probe_namespace": "node-startup-latency"},
            "environment": {"defender_sensor_present": False},
            "measurement": {"node_name": "n"},
        })


if __name__ == "__main__":
    unittest.main()
