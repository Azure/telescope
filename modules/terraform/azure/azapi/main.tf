locals {
  name = var.azapi_config.aks_name

  agent_pool_profiles = [{
    name   = var.azapi_config.default_node_pool.name
    count  = var.azapi_config.default_node_pool.count
    vmSize = var.azapi_config.default_node_pool.vm_size
    osType = var.azapi_config.default_node_pool.os_type
    mode   = var.azapi_config.default_node_pool.mode
  }]

  network_profile = var.azapi_config.network_profile != null ? {
    for k, v in {
      networkPlugin     = var.azapi_config.network_profile.network_plugin
      networkPluginMode = var.azapi_config.network_profile.network_plugin_mode
    } : k => v if v != null
  } : null

  properties = {
    for k, v in {
      kubernetesVersion = var.azapi_config.kubernetes_version
      dnsPrefix         = var.azapi_config.dns_prefix
      agentPoolProfiles = local.agent_pool_profiles
      networkProfile    = local.network_profile
      controlPlaneScalingProfile = var.azapi_config.control_plane_scaling_profile != null ? {
        scalingSize = var.azapi_config.control_plane_scaling_profile.scaling_size
      } : null
    } : k => v if v != null
  }

  body = {
    identity = {
      type = var.azapi_config.identity_type
    }
    sku = {
      name = var.azapi_config.sku.name
      tier = var.azapi_config.sku.tier
    }
    properties = local.properties
  }
}

data "azurerm_client_config" "current" {}

resource "azapi_resource" "aks_cluster" {
  type      = "Microsoft.ContainerService/managedClusters@${var.azapi_config.api_version}"
  name      = local.name
  parent_id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}"
  location  = var.location
  tags = merge(
    var.tags,
    {
      "role" = var.azapi_config.role
    },
  )

  body = local.body

  # disable so we can use preview api version
  schema_validation_enabled = false

  response_export_values = [
    "properties.fqdn"
  ]
}
