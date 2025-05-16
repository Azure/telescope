locals {
  region                   = lookup(var.json_input, "region", "East US")
  run_id                   = lookup(var.json_input, "run_id", "123456")
  aks_sku_tier             = lookup(var.json_input, "aks_sku_tier", null)
  aks_kubernetes_version   = lookup(var.json_input, "aks_kubernetes_version", null)
  aks_network_policy       = lookup(var.json_input, "aks_network_policy", null)
  aks_network_dataplane    = lookup(var.json_input, "aks_network_dataplane", null)
  aks_cli_system_node_pool = lookup(var.json_input, "aks_cli_system_node_pool", null)
  aks_cli_user_node_pool   = lookup(var.json_input, "aks_cli_user_node_pool", null)
  aks_custom_headers       = lookup(var.json_input, "aks_custom_headers", [])
  k8s_machine_type         = lookup(var.json_input, "k8s_machine_type", null)
  k8s_os_disk_type         = lookup(var.json_input, "k8s_os_disk_type", null)

  tags = {
    "owner"             = var.owner
    "scenario"          = "${var.scenario_type}-${var.scenario_name}"
    "creation_time"     = timestamp()
    "deletion_due_time" = timeadd(timestamp(), var.deletion_delay)
    "run_id"            = local.run_id
    "SkipAKSCluster"    = "1"
  }

  network_config_map = { for network in var.network_config_list : network.role => network }

  all_subnets = merge([for network in var.network_config_list : module.virtual_network[network.role].subnets]...)

  updated_aks_config_list = length(var.aks_config_list) > 0 ? [
    for aks in var.aks_config_list : merge(
      aks,
      {
        sku_tier           = local.aks_sku_tier != null ? local.aks_sku_tier : aks.sku_tier
        kubernetes_version = local.aks_kubernetes_version != null ? local.aks_kubernetes_version : aks.kubernetes_version
      }
    )
  ] : []

  aks_config_map = length(local.updated_aks_config_list) == 0 ? { for aks in var.aks_config_list : aks.role => aks } : { for aks in local.updated_aks_config_list : aks.role => aks }

  updated_aks_cli_config_list = length(var.aks_cli_config_list) > 0 ? [
    for aks in var.aks_cli_config_list : merge(
      aks,
      {
        sku_tier           = local.aks_sku_tier != null ? local.aks_sku_tier : aks.sku_tier
        kubernetes_version = local.aks_kubernetes_version != null ? local.aks_kubernetes_version : aks.kubernetes_version
        aks_custom_headers = length(local.aks_custom_headers) > 0 ? local.aks_custom_headers : aks.aks_custom_headers
        default_node_pool  = local.aks_cli_system_node_pool != null ? local.aks_cli_system_node_pool : aks.default_node_pool
        extra_node_pool    = local.aks_cli_user_node_pool != null ? local.aks_cli_user_node_pool : aks.extra_node_pool
      }
    )
  ] : []

  aks_cli_config_map = length(local.updated_aks_cli_config_list) == 0 ? { for aks in var.aks_cli_config_list : aks.role => aks } : { for aks in local.updated_aks_cli_config_list : aks.role => aks }
}

provider "azurerm" {
  features {}
}

module "public_ips" {
  source                = "./public-ip"
  resource_group_name   = local.run_id
  location              = local.region
  public_ip_config_list = var.public_ip_config_list
  tags                  = local.tags
}

module "virtual_network" {
  for_each = local.network_config_map

  source              = "./network"
  network_config      = each.value
  resource_group_name = local.run_id
  location            = local.region
  public_ips          = module.public_ips.pip_ids
  tags                = local.tags
}

module "aks" {
  for_each = local.aks_config_map

  source              = "./aks"
  resource_group_name = local.run_id
  location            = local.region
  aks_config          = each.value
  tags                = local.tags
  subnet_id           = try(local.all_subnets[each.value.subnet_name], null)
  vnet_id             = try(module.virtual_network[each.value.role].vnet_id, null)
  subnets             = try(local.all_subnets, null)
  k8s_machine_type    = local.k8s_machine_type
  k8s_os_disk_type    = local.k8s_os_disk_type
  network_dataplane   = local.aks_network_dataplane
  network_policy      = local.aks_network_policy
}

module "aks-cli" {
  for_each = local.aks_cli_config_map

  source              = "./aks-cli"
  resource_group_name = local.run_id
  location            = local.region
  aks_cli_config      = each.value
  tags                = local.tags
  subnet_id           = try(local.all_subnets[each.value.subnet_name], null)
  pod_subnet_id       = try(local.all_subnets[each.value.pod_subnet_name], null)
}
