locals {
  acr_config_map            = { for i, acr in var.acr_config_list : tostring(i) => acr }
  acr_private_dns_zone_name = length(var.acr_config_list) > 0 ? try(var.acr_config_list[0].private_endpoint.private_dns_zone_name, "privatelink.azurecr.io") : "privatelink.azurecr.io"
  acr_private_dns_enabled   = length([for acr in var.acr_config_list : acr if try(acr.private_endpoint != null, false)]) > 0

  # Plan-known switch for whether an aks-cli role needs a kubelet identity / AcrPull grants.
  # This is intentionally computed only from input configuration (acr_config_list), not from
  # any resource IDs, to keep downstream `count`/`for_each` stable during planning.
  acr_pull_enabled_by_aks_cli_role = {
    for role in var.aks_cli_roles : role => length([
      for acr in var.acr_config_list : 1
      if contains(
        concat(try(acr.acrpull_aks_cli_roles, []), try(acr.contributor_aks_cli_roles, [])),
        role
      )
    ]) > 0
  }

  acr_private_dns_vnet_roles = distinct([
    for acr in var.acr_config_list : var.subnet_to_network_role[acr.private_endpoint.subnet_name]
    if try(acr.private_endpoint != null, false)
  ])

  # Terraform doesn't have regexreplace(); replace() supports regex when pattern is wrapped in /.../
  acr_default_name_prefix = substr(replace(lower("acr${var.scenario_name}${var.run_id}"), "/[^0-9a-z]/", ""), 0, 45)

  acr_name_map = {
    for acr_key, acr in local.acr_config_map :
    acr_key => (acr.name != null ? acr.name : substr("${local.acr_default_name_prefix}${acr_key}", 0, 50))
  }

  acr_id_map = {
    for acr_key, acr_name in local.acr_name_map :
    acr_key => format(
      "/subscriptions/%s/resourceGroups/%s/providers/Microsoft.ContainerRegistry/registries/%s",
      data.azurerm_client_config.current.subscription_id,
      var.resource_group_name,
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

  acr_pull_scopes_by_aks_cli_role = {
    for role in var.aks_cli_roles : role => distinct(flatten([
      for acr_key, acr in local.acr_config_map : contains(
        distinct(concat(try(acr.acrpull_aks_cli_roles, []), try(acr.contributor_aks_cli_roles, []))),
        role
      ) ? [local.acr_id_map[acr_key]] : []
    ]))
  }

  bootstrap_container_registry_resource_id_by_aks_cli_role = {
    for role, scopes in local.acr_pull_scopes_by_aks_cli_role : role => try(scopes[0], null)
  }
}

data "azurerm_client_config" "current" {}

resource "azurerm_container_registry" "acr" {
  for_each = local.acr_config_map

  name                          = local.acr_name_map[each.key]
  resource_group_name           = var.resource_group_name
  location                      = var.location
  sku                           = each.value.sku
  admin_enabled                 = each.value.admin_enabled
  public_network_access_enabled = each.value.public_network_access_enabled
  tags                          = var.tags
}

resource "azurerm_private_dns_zone" "acr" {
  count = local.acr_private_dns_enabled ? 1 : 0

  name                = local.acr_private_dns_zone_name
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
  for_each = local.acr_private_dns_enabled ? { for role in local.acr_private_dns_vnet_roles : role => role } : {}

  name                  = "acr-dns-link-${each.key}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.acr[0].name
  virtual_network_id    = var.vnet_ids_by_role[each.key]
  registration_enabled  = false
  tags                  = var.tags
}

resource "azurerm_private_endpoint" "acr" {
  for_each = { for k, acr in local.acr_config_map : k => acr if try(acr.private_endpoint != null, false) }

  name                = "acr-pe-${each.key}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.subnet_ids_by_name[each.value.private_endpoint.subnet_name]
  tags                = var.tags

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

  depends_on = [azurerm_private_dns_zone_virtual_network_link.acr]
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
