locals {
  region                            = lookup(var.json_input, "region", "East US")
  run_id                            = lookup(var.json_input, "run_id", "123456")
  aks_sku_tier                      = lookup(var.json_input, "aks_sku_tier", null)
  aks_kubernetes_version            = lookup(var.json_input, "aks_kubernetes_version", null)
  aks_network_policy                = lookup(var.json_input, "aks_network_policy", null)
  aks_network_dataplane             = lookup(var.json_input, "aks_network_dataplane", null)
  aks_cli_system_node_pool          = lookup(var.json_input, "aks_cli_system_node_pool", null)
  aks_cli_user_node_pool            = lookup(var.json_input, "aks_cli_user_node_pool", null)
  aks_custom_headers                = lookup(var.json_input, "aks_custom_headers", [])
  k8s_machine_type                  = lookup(var.json_input, "k8s_machine_type", null)
  k8s_os_disk_type                  = lookup(var.json_input, "k8s_os_disk_type", null)
  aks_aad_enabled                   = lookup(var.json_input, "aks_aad_enabled", false)
  enable_apiserver_vnet_integration = lookup(var.json_input, "enable_apiserver_vnet_integration", false)
  public_key_path                   = lookup(var.json_input, "public_key_path", null)
  ssh_public_key                    = local.public_key_path != null ? (fileexists(local.public_key_path) ? file(local.public_key_path) : null) : null

  tags = merge(
    var.tags,
    {
      "owner"             = var.owner
      "scenario"          = "${var.scenario_type}-${var.scenario_name}"
      "creation_time"     = timestamp()
      "deletion_due_time" = timeadd(timestamp(), var.deletion_delay)
      "run_id"            = local.run_id
      "SkipAKSCluster"    = "1"
    }
  )

  network_config_map = { for network in var.network_config_list : network.role => network }

  subnet_to_network_role = merge([
    for network in var.network_config_list : {
      for subnet in network.subnet : subnet.name => network.role
    }
  ]...)

  route_table_config_map = { for rt in var.route_table_config_list : rt.name => rt }

  aks_cli_custom_config_path = "${path.cwd}/../../../scenarios/${var.scenario_type}/${var.scenario_name}/config/aks_custom_config.json"

  all_subnets              = merge([for network in var.network_config_list : module.virtual_network[network.role].subnets]...)
  all_nics                 = merge([for network in var.network_config_list : module.virtual_network[network.role].nics]...)
  all_key_vaults           = merge([for kv_name, kv in module.key_vault : { (kv_name) = kv.key_vaults }]...)
  all_disk_encryption_sets = merge([for des_name, des in module.disk_encryption_set : { (des_name) = des.disk_encryption_set_id }]...)
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
        sku_tier                          = local.aks_sku_tier != null ? local.aks_sku_tier : aks.sku_tier
        kubernetes_version                = local.aks_kubernetes_version != null ? local.aks_kubernetes_version : aks.kubernetes_version
        aks_custom_headers                = length(local.aks_custom_headers) > 0 ? local.aks_custom_headers : aks.aks_custom_headers
        default_node_pool                 = local.aks_cli_system_node_pool != null ? local.aks_cli_system_node_pool : aks.default_node_pool
        extra_node_pool                   = local.aks_cli_user_node_pool != null ? local.aks_cli_user_node_pool : aks.extra_node_pool
        enable_apiserver_vnet_integration = local.enable_apiserver_vnet_integration
      }
    )
  ] : []

  aks_cli_config_map = { for aks in local.updated_aks_cli_config_list : aks.role => aks }

  key_vault_config_map = { for kv in var.key_vault_config_list : kv.name => kv }

  vm_config_map = { for vm in var.vm_config_list : vm.role => vm }

  disk_encryption_set_config_map = { for des in var.disk_encryption_set_config_list : des.name => des }

  acr_config_map            = { for i, acr in var.acr_config_list : tostring(i) => acr }
  acr_private_dns_zone_name = length(var.acr_config_list) > 0 ? try(var.acr_config_list[0].private_endpoint.private_dns_zone_name, "privatelink.azurecr.io") : "privatelink.azurecr.io"
  acr_private_dns_enabled   = length([for acr in var.acr_config_list : acr if try(acr.private_endpoint != null, false)]) > 0

  acr_private_dns_vnet_roles = distinct([
    for acr in var.acr_config_list : local.subnet_to_network_role[acr.private_endpoint.subnet_name]
    if try(acr.private_endpoint != null, false)
  ])

  # Terraform doesn't have regexreplace(); replace() supports regex when pattern is wrapped in /.../
  acr_default_name_prefix = substr(replace(lower("acr${var.scenario_name}${local.run_id}"), "/[^0-9a-z]/", ""), 0, 45)

  # Compute ACR names/IDs from inputs so they are known at plan time.
  # We avoid depending on resource attributes here because downstream modules
  # need stable values for count/for_each.
  acr_name_map = {
    for acr_key, acr in local.acr_config_map :
    acr_key => (acr.name != null ? acr.name : substr("${local.acr_default_name_prefix}${acr_key}", 0, 50))
  }

  acr_id_map = {
    for acr_key, acr_name in local.acr_name_map :
    acr_key => format(
      "/subscriptions/%s/resourceGroups/%s/providers/Microsoft.ContainerRegistry/registries/%s",
      data.azurerm_client_config.current.subscription_id,
      local.run_id,
      acr_name
    )
  }

  acr_cache_rule_map = length(var.acr_config_list) > 0 ? merge([
    for acr_key, acr in local.acr_config_map : {
      for rule in try(acr.cache_rules, []) : "${acr_key}/${rule.name}" => {
        acr_key                    = acr_key
        name                       = rule.name
        source_repository          = rule.source_repository
        target_repository          = rule.target_repository
        credential_set_resource_id = try(rule.credential_set_resource_id, null)
      }
    }
  ]...) : {}

  aks_cli_acr_pull_scopes_map = {
    for role, _cfg in local.aks_cli_config_map : role => distinct(flatten([
      for acr_key, acr in local.acr_config_map : contains(
        distinct(concat(try(acr.acrpull_aks_cli_roles, []), try(acr.contributor_aks_cli_roles, []))),
        role
      ) ? [local.acr_id_map[acr_key]] : []
    ]))
  }

  aks_cli_bootstrap_container_registry_resource_id_map = {
    for role, scopes in local.aks_cli_acr_pull_scopes_map : role => try(scopes[0], null)
  }
}

data "azurerm_client_config" "current" {}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = false
    }
  }
}

provider "azapi" {
  skip_provider_registration = true
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

resource "azurerm_container_registry" "acr" {
  for_each = local.acr_config_map

  name                          = each.value.name != null ? each.value.name : substr("${local.acr_default_name_prefix}${each.key}", 0, 50)
  resource_group_name           = local.run_id
  location                      = local.region
  sku                           = each.value.sku
  admin_enabled                 = each.value.admin_enabled
  public_network_access_enabled = each.value.public_network_access_enabled
  tags                          = local.tags
}

resource "azurerm_private_dns_zone" "acr" {
  count = local.acr_private_dns_enabled ? 1 : 0

  name                = local.acr_private_dns_zone_name
  resource_group_name = local.run_id
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
  for_each = local.acr_private_dns_enabled ? { for role in local.acr_private_dns_vnet_roles : role => role } : {}

  name                  = "acr-dns-link-${each.key}"
  resource_group_name   = local.run_id
  private_dns_zone_name = azurerm_private_dns_zone.acr[0].name
  virtual_network_id    = module.virtual_network[each.key].vnet_id
  registration_enabled  = false
  tags                  = local.tags

  depends_on = [module.virtual_network, azurerm_private_dns_zone.acr]
}

resource "azurerm_private_endpoint" "acr" {
  for_each = { for k, acr in local.acr_config_map : k => acr if try(acr.private_endpoint != null, false) }

  name                = "acr-pe-${each.key}"
  location            = local.region
  resource_group_name = local.run_id
  subnet_id           = local.all_subnets[each.value.private_endpoint.subnet_name]
  tags                = local.tags

  private_service_connection {
    name                           = "acr-psc-${each.key}"
    private_connection_resource_id = azurerm_container_registry.acr[each.key].id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "acr-dns-${each.key}"
    private_dns_zone_ids = [azurerm_private_dns_zone.acr[0].id]
  }

  depends_on = [module.virtual_network, azurerm_private_dns_zone_virtual_network_link.acr]
}

resource "azapi_resource" "acr_cache_rule" {
  for_each = local.acr_cache_rule_map

  type      = "Microsoft.ContainerRegistry/registries/cacheRules@2023-07-01"
  name      = each.value.name
  parent_id = azurerm_container_registry.acr[each.value.acr_key].id

  body = {
    properties = merge(
      {
        sourceRepository = each.value.source_repository
        targetRepository = each.value.target_repository
      },
      each.value.credential_set_resource_id != null ? { credentialSetResourceId = each.value.credential_set_resource_id } : {}
    )
  }

  depends_on = [azurerm_container_registry.acr]
}

module "dns_zones" {

  source              = "./dns-zone"
  resource_group_name = local.run_id
  dns_zones           = var.dns_zones
  tags                = local.tags
}

module "firewall" {
  source = "./firewall"

  firewall_config_list = var.firewall_config_list
  subnets_map          = local.all_subnets
  public_ips_map       = module.public_ips.pip_ids
  resource_group_name  = local.run_id
  location             = local.region
  tags                 = local.tags

  depends_on = [module.virtual_network]
}

module "route_table" {
  for_each = local.route_table_config_map

  source = "./route-table"

  route_table_config   = each.value
  resource_group_name  = local.run_id
  location             = local.region
  subnets_ids          = local.all_subnets
  firewall_private_ips = module.firewall.firewall_private_ips
  public_ips           = module.public_ips.pip_ids
  tags                 = local.tags

  depends_on = [module.virtual_network, module.firewall]
}

module "key_vault" {
  for_each = local.key_vault_config_map

  source              = "./key-vault"
  resource_group_name = local.run_id
  location            = local.region
  key_vault_config    = each.value
  tags                = local.tags
}

module "disk_encryption_set" {
  for_each = local.disk_encryption_set_config_map

  source                     = "./disk-encryption-set"
  resource_group_name        = local.run_id
  location                   = local.region
  disk_encryption_set_config = each.value
  key_vaults                 = local.all_key_vaults
  tags                       = local.tags

  depends_on = [module.key_vault]
}

module "aks" {
  for_each = local.aks_config_map

  source               = "./aks"
  resource_group_name  = local.run_id
  location             = local.region
  aks_config           = each.value
  tags                 = local.tags
  subnet_id            = try(local.all_subnets[each.value.subnet_name], null)
  vnet_id              = try(module.virtual_network[each.value.role].vnet_id, null)
  subnets              = try(local.all_subnets, null)
  k8s_machine_type     = local.k8s_machine_type
  k8s_os_disk_type     = local.k8s_os_disk_type
  network_dataplane    = local.aks_network_dataplane
  network_policy       = local.aks_network_policy
  dns_zones            = try(module.dns_zones.dns_zone_ids, null)
  aks_aad_enabled      = local.aks_aad_enabled
  key_vaults           = local.all_key_vaults
  disk_encryption_sets = local.all_disk_encryption_sets
  depends_on           = [module.route_table, module.virtual_network, module.disk_encryption_set]
}

module "aks-cli" {
  for_each = local.aks_cli_config_map

  source                     = "./aks-cli"
  resource_group_name        = local.run_id
  location                   = local.region
  aks_cli_config             = each.value
  tags                       = local.tags
  subnets_map                = local.all_subnets
  aks_cli_custom_config_path = local.aks_cli_custom_config_path
  key_vaults                 = local.all_key_vaults
  aks_aad_enabled            = local.aks_aad_enabled

  acr_pull_scopes = local.aks_cli_acr_pull_scopes_map[each.key]

  # For network isolated clusters (BYO ACR), pass the registry resource ID into az aks create.
  bootstrap_artifact_source                = local.aks_cli_bootstrap_container_registry_resource_id_map[each.key] != null ? "Cache" : null
  bootstrap_container_registry_resource_id = local.aks_cli_bootstrap_container_registry_resource_id_map[each.key]

  disk_encryption_sets = local.all_disk_encryption_sets
  depends_on = [
    module.route_table,
    module.virtual_network,
    module.disk_encryption_set,
    azurerm_container_registry.acr,
    azapi_resource.acr_cache_rule,
    azurerm_private_endpoint.acr,
    azurerm_private_dns_zone_virtual_network_link.acr,
  ]
}

module "virtual_machine" {
  for_each = local.ssh_public_key != null ? local.vm_config_map : {}

  source              = "./virtual-machine"
  resource_group_name = local.run_id
  location            = local.region
  tags                = local.tags
  ssh_public_key      = local.ssh_public_key
  vm_config           = each.value
  nics_map            = local.all_nics

  # Ensure AKS cluster is created before VM tries to look it up for RBAC
  depends_on = [module.aks, module.aks-cli]
}
