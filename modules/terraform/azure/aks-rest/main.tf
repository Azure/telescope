locals {
  tags_map = merge(var.tags, { "role" = var.aks_rest_config.role })

  # Subnet ID resolution
  aks_subnet_id = (
    var.aks_rest_config.subnet_name == null ?
    null :
    try(var.subnets_map[var.aks_rest_config.subnet_name], null)
  )

  # KMS configuration
  key_management_service = (
    var.aks_rest_config.kms_config != null
    ) ? {
    key_vault_id = try(
      var.key_vaults[var.aks_rest_config.kms_config.key_vault_name].id,
      error("Specified kms_key_vault_name '${var.aks_rest_config.kms_config.key_vault_name}' does not exist in Key Vaults: ${join(", ", keys(var.key_vaults))}")
    )
    key_vault_key_id = try(
      var.key_vaults[var.aks_rest_config.kms_config.key_vault_name].keys[var.aks_rest_config.kms_config.key_name].id,
      error("Specified kms_key_name '${var.aks_rest_config.kms_config.key_name}' does not exist in Key Vault '${var.aks_rest_config.kms_config.key_vault_name}' keys: ${join(", ", keys(var.key_vaults[var.aks_rest_config.kms_config.key_vault_name].keys))}")
    )
    key_vault_key_resource_id = try(
      var.key_vaults[var.aks_rest_config.kms_config.key_vault_name].keys[var.aks_rest_config.kms_config.key_name].resource_id,
      error("Specified kms_key_name '${var.aks_rest_config.kms_config.key_name}' does not exist in Key Vault '${var.aks_rest_config.kms_config.key_vault_name}' keys: ${join(", ", keys(var.key_vaults[var.aks_rest_config.kms_config.key_vault_name].keys))}")
    )
  } : null

  # Disk Encryption Set
  disk_encryption_set_id = (
    var.aks_rest_config.disk_encryption_set_name != null ?
    try(
      var.disk_encryption_sets[var.aks_rest_config.disk_encryption_set_name],
      error("Specified disk_encryption_set_name '${var.aks_rest_config.disk_encryption_set_name}' does not exist in Disk Encryption Sets: ${join(", ", keys(var.disk_encryption_sets))}")
    ) : null
  )

  # REST API URL
  rest_api_url = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.ContainerService/managedClusters/${var.aks_rest_config.aks_name}?api-version=${var.aks_rest_config.api_version}"

  # Agent pool profiles
  agent_pool_profiles = concat(
    var.aks_rest_config.default_node_pool != null ? [merge(
      {
        name   = var.aks_rest_config.default_node_pool.name
        mode   = var.aks_rest_config.default_node_pool.mode
        count  = var.aks_rest_config.default_node_pool.node_count
        vmSize = var.aks_rest_config.default_node_pool.vm_size
        osType = var.aks_rest_config.default_node_pool.os_type
      },
      local.aks_subnet_id != null ? { vnetSubnetID = local.aks_subnet_id } : {}
    )] : [],
    [
      for pool in var.aks_rest_config.extra_node_pool : merge(
        {
          name   = pool.name
          mode   = pool.mode
          count  = pool.node_count
          vmSize = pool.vm_size
          osType = pool.os_type
        },
        local.aks_subnet_id != null ? { vnetSubnetID = local.aks_subnet_id } : {}
      )
    ]
  )

  # Build properties block conditionally
  properties = merge(
    {
      dnsPrefix         = coalesce(var.aks_rest_config.dns_prefix, var.aks_rest_config.aks_name)
      agentPoolProfiles = local.agent_pool_profiles
      networkProfile = {
        networkPlugin     = var.aks_rest_config.network_plugin
        networkPluginMode = var.aks_rest_config.network_plugin_mode
      }
    },
    # Conditionally add kubernetesVersion
    var.aks_rest_config.kubernetes_version != null ? {
      kubernetesVersion = var.aks_rest_config.kubernetes_version
    } : {},
    # Conditionally add controlPlaneScalingProfile
    var.aks_rest_config.control_plane_scaling_size != null ? {
      controlPlaneScalingProfile = {
        scalingSize = var.aks_rest_config.control_plane_scaling_size
      }
    } : {},
    # Conditionally add KMS security profile
    local.key_management_service != null ? {
      securityProfile = {
        azureKeyVaultKms = {
          enabled               = true
          keyId                 = local.key_management_service.key_vault_key_id
          keyVaultNetworkAccess = var.aks_rest_config.kms_config.network_access
        }
      }
    } : {},
    # Conditionally add disk encryption set
    local.disk_encryption_set_id != null ? {
      diskEncryptionSetID = local.disk_encryption_set_id
    } : {}
  )

  # Identity block
  # Derive identity type from the presence of a managed identity name to keep
  # the request body consistent with the actual identity resource creation.
  identity_block = (
    var.aks_rest_config.managed_identity_name != null &&
    var.aks_rest_config.managed_identity_name != ""
  ) ? {
    type = "UserAssigned"
    userAssignedIdentities = {
      (azurerm_user_assigned_identity.userassignedidentity[0].id) = {}
    }
  } : {
    type = "SystemAssigned"
  }

  # Full request body
  request_body = jsonencode({
    location   = var.location
    identity   = local.identity_block
    properties = local.properties
    tags       = local.tags_map
    sku = {
      name = var.aks_rest_config.sku_name
      tier = var.aks_rest_config.sku_tier
    }
  })

  # Custom headers flags for az rest command
  custom_headers_flags = join(" ", [
    for header in var.aks_rest_config.custom_headers :
    format("%s %s", "--headers", format("\"%s\"", header))
  ])

  # az rest PUT command followed by az aks wait to block until provisioning completes
  # az rest returns immediately (no LRO polling), so we must wait explicitly
  az_rest_put_command = join(" && ", compact([
    join(" ", compact([
      "az", "rest",
      "--method", "PUT",
      "--url", format("\"%s\"", local.rest_api_url),
      "--headers", "\"Content-Type=application/json\"",
      local.custom_headers_flags,
      "--body", format("'%s'", local.request_body),
    ])),
    join(" ", [
      "az", "aks", "wait", "--created",
      "-g", var.resource_group_name,
      "-n", var.aks_rest_config.aks_name,
    ]),
  ]))

  # az aks delete command (reuse standard CLI for deletion)
  az_rest_delete_command = join(" ", [
    "az", "aks", "delete",
    "-g", var.resource_group_name,
    "-n", var.aks_rest_config.aks_name,
    "--yes",
  ])

  # KMS role assignments
  aks_kms_role_assignments = var.aks_rest_config.managed_identity_name != null && local.key_management_service != null ? {
    "Key Vault Crypto Service Encryption User" = local.key_management_service.key_vault_key_resource_id
    "Key Vault Crypto User"                    = local.key_management_service.key_vault_id
  } : {}
}

data "azurerm_client_config" "current" {}

resource "azurerm_user_assigned_identity" "userassignedidentity" {
  count               = var.aks_rest_config.managed_identity_name == null ? 0 : 1
  location            = var.location
  name                = var.aks_rest_config.managed_identity_name
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "network_contributor" {
  count                = var.aks_rest_config.managed_identity_name != null && var.aks_rest_config.subnet_name != null ? 1 : 0
  role_definition_name = "Network Contributor"
  scope                = local.aks_subnet_id
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

# Grant AKS identity KMS-related Key Vault roles
resource "azurerm_role_assignment" "aks_identity_kms_roles" {
  for_each             = local.aks_kms_role_assignments
  scope                = each.value
  role_definition_name = each.key
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

resource "terraform_data" "aks_rest" {
  depends_on = [
    azurerm_role_assignment.network_contributor,
    azurerm_role_assignment.aks_identity_kms_roles
  ]

  input = {
    az_rest_put_command    = var.aks_rest_config.dry_run ? "echo ${jsonencode(local.az_rest_put_command)}" : local.az_rest_put_command,
    az_rest_delete_command = var.aks_rest_config.dry_run ? "echo ${jsonencode(local.az_rest_delete_command)}" : local.az_rest_delete_command
  }

  provisioner "local-exec" {
    command = self.input.az_rest_put_command
  }

  provisioner "local-exec" {
    when    = destroy
    command = self.input.az_rest_delete_command
  }
}

# Fetch AKS cluster to get identities for DES role assignments
data "azurerm_kubernetes_cluster" "aks" {
  count = var.aks_rest_config.disk_encryption_set_name != null && !var.aks_rest_config.dry_run ? 1 : 0

  depends_on = [terraform_data.aks_rest]

  name                = var.aks_rest_config.aks_name
  resource_group_name = var.resource_group_name
}

# Grant Reader access to Disk Encryption Set for kubelet identity
resource "azurerm_role_assignment" "des_reader_kubelet" {
  count = var.aks_rest_config.disk_encryption_set_name != null && !var.aks_rest_config.dry_run ? 1 : 0

  scope                = local.disk_encryption_set_id
  role_definition_name = "Reader"
  principal_id         = data.azurerm_kubernetes_cluster.aks[0].kubelet_identity[0].object_id
}

# Grant Reader access to Disk Encryption Set for cluster identity
resource "azurerm_role_assignment" "des_reader_cluster" {
  count = var.aks_rest_config.disk_encryption_set_name != null && !var.aks_rest_config.dry_run ? 1 : 0

  scope                = local.disk_encryption_set_id
  role_definition_name = "Reader"
  principal_id         = var.aks_rest_config.managed_identity_name != null ? azurerm_user_assigned_identity.userassignedidentity[0].principal_id : data.azurerm_kubernetes_cluster.aks[0].identity[0].principal_id
}
