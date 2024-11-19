locals {

}


resource "google_container_cluster" "default" {
  name       = var.gke_config.name
  network    = google_compute_network.default.id
  subnetwork = google_compute_subnetwork.default.id

  node_pool {
    name       = "default"
    node_count = 1
    version    = "1.16.15-gke.4300"
  }

  deletion_protection = false
}
