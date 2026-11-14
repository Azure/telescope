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
      enableRBAC        = var.azapi_config.aad_enabled ? true : null
      aadProfile = var.azapi_config.aad_enabled ? {
        managed         = true
        enableAzureRBAC = true
        tenantID        = data.azurerm_client_config.current.tenant_id
      } : null
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

  timeouts {
    create = "60m"
  }
}

resource "azurerm_role_definition" "metrics_reader" {
  count = var.azapi_config.metrics_reader_enabled ? 1 : 0

  name        = "${var.resource_group_name}-${local.name}-metrics-reader"
  scope       = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}"
  description = "Read the AKS API server metrics endpoint."

  permissions {
    data_actions = ["Microsoft.ContainerService/managedClusters/metrics/read"]
  }

  assignable_scopes = ["/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}"]
}

resource "azurerm_role_assignment" "metrics_reader" {
  count = var.azapi_config.metrics_reader_enabled ? 1 : 0

  scope              = azapi_resource.aks_cluster.id
  role_definition_id = azurerm_role_definition.metrics_reader[0].role_definition_resource_id
  principal_id       = data.azurerm_client_config.current.object_id
}
