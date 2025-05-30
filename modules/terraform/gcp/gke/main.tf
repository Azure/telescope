locals {
  extra_nodepool_config_map = { for nodepool in var.gke_config.extra_node_pools : nodepool.name => nodepool }
}

resource "google_container_cluster" "gke" {
  name       = "${var.gke_config.name}-${substr(var.run_id, 0, 8)}"
  network    = var.vpc_id
  subnetwork = var.subnet_id

  node_pool {
    name       = var.gke_config.default_node_pool.name
    node_count = var.gke_config.default_node_pool.node_count

    node_config {
      machine_type = var.gke_config.default_node_pool.machine_type
      disk_size_gb = 50
    }
  }

  resource_labels     = var.labels
  deletion_protection = false
}


resource "google_container_node_pool" "node_pool" {
  for_each   = local.extra_nodepool_config_map
  name       = each.key
  cluster    = google_container_cluster.gke.id
  node_count = each.value.node_count
  node_config {
    machine_type = each.value.machine_type
    disk_size_gb = 50
  }
}
