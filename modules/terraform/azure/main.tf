locals {
  region                   = lookup(var.json_input, "region", "East US")
  run_id                   = lookup(var.json_input, "run_id", "123456")
  aks_sku_tier             = lookup(var.json_input, "aks_sku_tier", "Standard")
  aks_network_policy       = lookup(var.json_input, "aks_network_policy", null)
  aks_cli_system_node_pool = lookup(var.json_input, "aks_cli_system_node_pool", null)
  aks_cli_user_node_pool   = lookup(var.json_input, "aks_cli_user_node_pool", null)
  aks_custom_headers       = lookup(var.json_input, "aks_custom_headers", [])

  tags = {
    "owner"             = var.owner
    "scenario"          = "${var.scenario_type}-${var.scenario_name}"
    "creation_time"     = timestamp()
    "deletion_due_time" = timeadd(timestamp(), var.deletion_delay)
    "run_id"            = local.run_id
  }

  updated_aks_config_list = length(var.aks_config_list) == 1 ? [
    for aks in var.aks_config_list : merge(
      aks,
      {
        sku_tier = length(local.aks_sku_tier) > 0 ? local.aks_sku_tier : aks.sku_tier
        network_profile = merge(
          aks.network_profile,
          {
            network_policy  = local.aks_network_policy != null ? local.aks_network_policy : aks.network_profile.network_policy
            ebpf_data_plane = local.aks_network_policy != null && local.aks_network_policy == "cilium" ? local.aks_network_policy : aks.network_profile.ebpf_data_plane
          }
        )
      }
    )
  ] : []

  aks_config_map = length(local.updated_aks_config_list) == 0 ? { for aks in var.aks_config_list : aks.role => aks } : { for aks in local.updated_aks_config_list : aks.role => aks }

  updated_aks_cli_config_list = length(var.aks_cli_config_list) == 1 ? [
    for aks in var.aks_cli_config_list : merge(
      aks,
      {
        sku_tier           = length(local.aks_sku_tier) > 0 ? local.aks_sku_tier : aks.sku_tier
        aks_custom_headers = length(local.aks_custom_headers) > 0 ? local.aks_custom_headers : aks.aks_custom_headers
        default_node_pool  = local.aks_cli_system_node_pool != null ? local.aks_cli_system_node_pool : aks.default_node_pool
        extra_node_pool    = local.aks_cli_user_node_pool != null ? local.aks_cli_user_node_pool : aks.extra_node_pool
      }
    )
  ] : []

  aks_cli_config_map = length(local.updated_aks_cli_config_list) == 0 ? { for aks in var.aks_cli_config_list : aks.role => aks } : { for aks in local.updated_aks_cli_config_list : aks.role => aks }
}

terraform {
  required_version = ">=1.5.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "<= 3.93.0"
    }
  }
}

provider "azurerm" {
  features {}
}

module "aks" {
  for_each = local.aks_config_map

  source              = "./aks"
  resource_group_name = local.run_id
  location            = local.region
  aks_config          = each.value
  tags                = local.tags
}

module "aks-cli" {
  for_each = local.aks_cli_config_map

  source              = "./aks-cli"
  resource_group_name = local.run_id
  location            = local.region
  aks_cli_config      = each.value
  tags                = local.tags
}
