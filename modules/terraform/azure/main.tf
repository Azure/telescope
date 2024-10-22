locals {
  region                   = lookup(var.json_input, "region", "East US")
  run_id                   = lookup(var.json_input, "run_id", "123456")
  aks_cli_sku_tier         = lookup(var.json_input, "aks_cli_sku_tier", "standard")
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

  aks_config_map = { for aks in var.aks_config_list : aks.role => aks }

  updated_aks_cli_config_list = (length(var.aks_cli_config_list) == 1) ? flatten([
    for aks in var.aks_cli_config_list : [
      {
        role                          = aks.role
        aks_name                      = aks.aks_name
        sku_tier                      = length(local.aks_cli_sku_tier) > 0 ? local.aks_cli_sku_tier : aks.sku_tier
        aks_custom_headers            = length(local.aks_custom_headers) > 0 ? local.aks_custom_headers : aks.aks_custom_headers
        use_aks_preview_cli_extension = aks.use_aks_preview_cli_extension
        default_node_pool             = local.aks_cli_system_node_pool != null ? local.aks_cli_system_node_pool : aks.default_node_pool
        extra_node_pool               = local.aks_cli_user_node_pool != null ? local.aks_cli_user_node_pool : aks.extra_node_pool
        optional_parameters           = aks.optional_parameters
      }
    ]
  ]) : []

  aks_cli_config_map = length(local.updated_aks_cli_config_list) == 0 ? { for aks in var.aks_cli_config_list : aks.role => aks } : { for aks in local.updated_aks_cli_config_list : aks.role => aks }
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
