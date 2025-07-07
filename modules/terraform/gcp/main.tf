locals {
  project_id = lookup(var.json_input, "project_id", null)
  region     = lookup(var.json_input, "region", "us-central1")
  run_id     = lookup(var.json_input, "run_id", "123456")

  labels = {
    "owner"    = var.owner
    "scenario" = "${var.scenario_type}-${var.scenario_name}"
    "run_id"   = local.run_id
  }
  network_config_map = { for network in var.network_config_list : network.role => network }
  gke_config_map     = { for gke_config in var.gke_config_list : gke_config.name => gke_config }

  all_subnets = merge([for network in var.network_config_list : module.network[network.role].subnets]...)
}


module "network" {
  source = "./network"

  for_each = local.network_config_map

  network_config = each.value
  run_id         = local.run_id
}

module "gke" {
  source = "./gke"

  for_each = local.gke_config_map

  gke_config = each.value
  subnet_id  = try(local.all_subnets["${each.value.subnet_name}-${local.run_id}"], null)
  vpc_id     = try(module.network[each.value.role].vpc_id, null)
  labels     = local.labels
  run_id     = local.run_id
}
