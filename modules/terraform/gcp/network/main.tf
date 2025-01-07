locals {
  input_subnet_map   = { for subnet in var.network_config.subnets : subnet.name => subnet }
  input_firewall_map = { for firewall in var.network_config.firewall_rules : firewall.name => firewall }
}

resource "google_compute_network" "vpc" {
  name                    = "${var.network_config.vpc_name}-${var.run_id}"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnets" {
  for_each = local.input_subnet_map

  name          = "${each.value.name}-${var.run_id}"
  ip_cidr_range = each.value.cidr
  network       = google_compute_network.vpc.id

  dynamic "secondary_ip_range" {
    for_each = each.value.secondary_ip_ranges != null ? each.value.secondary_ip_ranges : []
    content {
      range_name    = secondary_ip_range.value.range_name
      ip_cidr_range = secondary_ip_range.value.ip_cidr_range
    }

  }
}

resource "google_compute_firewall" "firewall" {
  for_each           = local.input_firewall_map
  name               = "${each.value.name}-${var.run_id}"
  network            = google_compute_network.vpc.name
  direction          = each.value.direction
  priority           = each.value.priority
  source_ranges      = each.value.source_ranges
  destination_ranges = each.value.destination_ranges
  source_tags        = each.value.source_tags
  target_tags        = each.value.target_tags

  dynamic "allow" {
    for_each = each.value.allow
    content {
      protocol = allow.value.protocol
      ports    = allow.value.ports
    }
  }
}
