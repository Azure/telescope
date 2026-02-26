locals {
  tags_list = [
    for key, value in merge(var.tags, { "role" = var.aks_cli_config.role }) :
    format("%s=%s", key, value)
  ]

  acr_pull_scopes = distinct(concat(var.acr_pull_scopes, var.acr_contributor_scopes))

  extra_pool_map = {
    for pool in var.aks_cli_config.extra_node_pool :
    pool.name => pool
  }

  key_management_service = (
    var.aks_cli_config.kms_config != null
    ) ? {
    key_vault_id = try(
      var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].id,
      error("Specified kms_key_vault_name '${var.aks_cli_config.kms_config.key_vault_name}' does not exist in Key Vaults: ${join(", ", keys(var.key_vaults))}")
    )
    key_vault_key_id = try(
      var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].keys[var.aks_cli_config.kms_config.key_name].id,
      error("Specified kms_key_name '${var.aks_cli_config.kms_config.key_name}' does not exist in Key Vault '${var.aks_cli_config.kms_config.key_vault_name}' keys: ${join(", ", keys(var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].keys))}")
    )
    key_vault_key_resource_id = try(
      var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].keys[var.aks_cli_config.kms_config.key_name].resource_id,
      error("Specified kms_key_name '${var.aks_cli_config.kms_config.key_name}' does not exist in Key Vault '${var.aks_cli_config.kms_config.key_vault_name}' keys: ${join(", ", keys(var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].keys))}")
    )
  } : null

  # Disk Encryption Set for OS disk encryption with Customer-Managed Keys
  # Reference: https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys
  disk_encryption_set_id = (
    var.aks_cli_config.disk_encryption_set_name != null ?
    try(
      var.disk_encryption_sets[var.aks_cli_config.disk_encryption_set_name],
      error("Specified disk_encryption_set_name '${var.aks_cli_config.disk_encryption_set_name}' does not exist in Disk Encryption Sets: ${join(", ", keys(var.disk_encryption_sets))}")
    ) : null
  )

  kubernetes_version = (
    var.aks_cli_config.kubernetes_version == null ?
    "" :
    format(
      "%s %s",
      "--kubernetes-version", var.aks_cli_config.kubernetes_version,
    )
  )

  aks_subnet_id = (
    var.aks_cli_config.subnet_name == null ?
    null :
    try(var.subnets_map[var.aks_cli_config.subnet_name], null)
  )
  api_server_subnet_id = (
    var.aks_cli_config.api_server_subnet_name == null ?
    null :
    try(var.subnets_map[var.aks_cli_config.api_server_subnet_name], null)
  )

  aks_custom_headers_flags = (
    length(var.aks_cli_config.aks_custom_headers) == 0 ?
    "" :
    format(
      "%s %s",
      "--aks-custom-headers",
      join(",", var.aks_cli_config.aks_custom_headers),
    )
  )

  optional_parameters = (
    length(var.aks_cli_config.optional_parameters) == 0 ?
    "" :
    join(" ", [
      for param in var.aks_cli_config.optional_parameters :
      format("--%s %s", param.name, param.value)
    ])
  )


  kms_parameters = (
    local.key_management_service == null || var.aks_cli_config.managed_identity_name == null ?
    "" :
    join(" ", [
      "--enable-azure-keyvault-kms",
      format("--azure-keyvault-kms-key-id %s", local.key_management_service.key_vault_key_id),
      format("--azure-keyvault-kms-key-vault-network-access %s", var.aks_cli_config.kms_config.network_access)
    ])
  )

  aks_kms_role_assignments = var.aks_cli_config.managed_identity_name != null && local.key_management_service != null ? {
    "Key Vault Crypto Service Encryption User" = local.key_management_service.key_vault_key_resource_id
    "Key Vault Crypto User"                    = local.key_management_service.key_vault_id
  } : {}

  # Disk Encryption Set parameters for OS disk encryption with Customer-Managed Keys
  disk_encryption_parameters = (
    local.disk_encryption_set_id == null ?
    "" :
    format("--node-osdisk-diskencryptionset-id %s", local.disk_encryption_set_id)
  )

  subnet_id_parameter = (local.aks_subnet_id == null ?
    "" :
    format(
      "%s %s",
      "--vnet-subnet-id", local.aks_subnet_id,
    )
  )

  managed_identity_parameter = (var.aks_cli_config.managed_identity_name == null ?
    "--enable-managed-identity" :
    format(
      "%s %s",
      "--assign-identity", azurerm_user_assigned_identity.userassignedidentity[0].id,
    )
  )

  kubelet_identity_parameter = (length(local.acr_pull_scopes) == 0 ?
    "" :
    format(
      "%s %s",
      "--assign-kubelet-identity", azurerm_user_assigned_identity.kubelet_identity[0].id,
    )
  )

  bootstrap_parameters = join(" ", compact([
    var.bootstrap_artifact_source != null ? format("--bootstrap-artifact-source %s", var.bootstrap_artifact_source) : null,
    var.bootstrap_container_registry_resource_id != null ? format("--bootstrap-container-registry-resource-id %s", var.bootstrap_container_registry_resource_id) : null,
  ]))


  api_server_vnet_integration_parameter = (var.aks_cli_config.enable_apiserver_vnet_integration && local.api_server_subnet_id != null ?
    format(
      "--enable-apiserver-vnet-integration --apiserver-subnet-id %s",
      local.api_server_subnet_id,
    ) :
    ""
  )

  aad_parameter = (
    var.aks_aad_enabled == true ?
    format(
      "--enable-aad --enable-azure-rbac --aad-admin-group-object-ids %s --aad-tenant-id %s",
      data.azurerm_client_config.current.object_id,
      data.azurerm_client_config.current.tenant_id
    )
    : ""
  )

  custom_configurations = (
    var.aks_cli_config.use_custom_configurations && var.aks_cli_custom_config_path != null ?
    format(
      "--custom-configuration %s",
      var.aks_cli_custom_config_path
    ) :
    ""
  )

  default_node_pool_parameters = (
    var.aks_cli_config.default_node_pool == null ? [] : [
      "--nodepool-name", var.aks_cli_config.default_node_pool.name,
      "--node-count", var.aks_cli_config.default_node_pool.node_count,
      "--node-vm-size", var.aks_cli_config.default_node_pool.vm_size,
      "--vm-set-type", var.aks_cli_config.default_node_pool.vm_set_type,
      "--node-osdisk-type", var.aks_cli_config.default_node_pool.os_disk_type,
    ]
  )

  aks_cli_command = join(" ", concat([
    "az",
    "aks",
    "create",
    "-g", var.resource_group_name,
    "-n", var.aks_cli_config.aks_name,
    "--location", var.location,
    "--tier", var.aks_cli_config.sku_tier,
    "--tags", join(" ", local.tags_list),
    local.aks_custom_headers_flags,
    local.custom_configurations,
    "--no-ssh-key",
    local.kubernetes_version,
    local.bootstrap_parameters,
    local.optional_parameters,
    local.kms_parameters,
    local.disk_encryption_parameters,
    local.subnet_id_parameter,
    local.managed_identity_parameter,
    local.kubelet_identity_parameter,
    local.api_server_vnet_integration_parameter,
    local.aad_parameter,
  ], local.default_node_pool_parameters))

  aks_cli_destroy_command = join(" ", [
    "az",
    "aks",
    "delete",
    "-g", var.resource_group_name,
    "-n", var.aks_cli_config.aks_name,
    "--yes",
  ])
}

data "azurerm_client_config" "current" {}

locals {
  resource_group_id = format(
    "/subscriptions/%s/resourceGroups/%s",
    data.azurerm_client_config.current.subscription_id,
    var.resource_group_name
  )
}

resource "azurerm_user_assigned_identity" "userassignedidentity" {
  count               = var.aks_cli_config.managed_identity_name == null ? 0 : 1
  location            = var.location
  name                = var.aks_cli_config.managed_identity_name
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_user_assigned_identity" "kubelet_identity" {
  count               = length(local.acr_pull_scopes) == 0 ? 0 : 1
  location            = var.location
  name                = "${var.aks_cli_config.aks_name}-kubelet-identity"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "network_contributor" {
  count                = var.aks_cli_config.managed_identity_name != null && var.aks_cli_config.subnet_name != null ? 1 : 0
  role_definition_name = "Network Contributor"
  scope                = local.aks_subnet_id
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

resource "azurerm_role_assignment" "network_contributor_api_server_subnet" {
  count = (var.aks_cli_config.managed_identity_name != null && var.aks_cli_config.enable_apiserver_vnet_integration) ? 1 : 0

  role_definition_name = "Network Contributor"
  scope                = local.api_server_subnet_id
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

# Grant AcrPull access to ACR for kubelet identity (node identity) BEFORE cluster creation.
resource "azurerm_role_assignment" "acr_pull_kubelet" {
  for_each = (!var.aks_cli_config.dry_run && length(local.acr_pull_scopes) > 0) ? toset(local.acr_pull_scopes) : toset([])

  scope                = each.value
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.kubelet_identity[0].principal_id
}

# If the cluster uses a user-assigned identity, it must be able to assign/use the kubelet identity.
resource "azurerm_role_assignment" "managed_identity_operator_kubelet" {
  count = (!var.aks_cli_config.dry_run && length(local.acr_pull_scopes) > 0 && var.aks_cli_config.managed_identity_name != null) ? 1 : 0

  scope                = azurerm_user_assigned_identity.kubelet_identity[0].id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

resource "terraform_data" "enable_aks_cli_preview_extension" {
  count = var.aks_cli_config.use_aks_preview_cli_extension == true ? 1 : 0

  # Todo - Update aks-preview extension for newer features
  provisioner "local-exec" {
    command = var.aks_cli_config.use_aks_preview_private_build == true ? (
      <<EOT
			wget https://telescopetools.z13.web.core.windows.net/packages/az-cli/aks_preview-14.0.0b6-py2.py3-none-any.whl
			az extension add --source ./aks_preview-14.0.0b6-py2.py3-none-any.whl -y
			az version
    EOT
      ) : (
      <<EOT
      az extension add -n aks-preview --version 19.0.0b5
      az version
    EOT
    )
  }

  provisioner "local-exec" {
    when    = destroy
    command = "az extension remove -n aks-preview 2>/dev/null || true"
  }
}

resource "terraform_data" "aks_cli" {
  depends_on = [
    terraform_data.enable_aks_cli_preview_extension,
    azurerm_role_assignment.network_contributor,
    azurerm_role_assignment.network_contributor_api_server_subnet,
    azurerm_role_assignment.aks_identity_kms_roles,
    azurerm_role_assignment.acr_pull_kubelet,
    azurerm_role_assignment.managed_identity_operator_kubelet
  ]

  input = {
    aks_cli_command         = var.aks_cli_config.dry_run ? "echo '${local.aks_cli_command}'" : local.aks_cli_command,
    aks_cli_destroy_command = var.aks_cli_config.dry_run ? "echo '${local.aks_cli_destroy_command}'" : local.aks_cli_destroy_command
  }

  provisioner "local-exec" {
    command = self.input.aks_cli_command
  }

  provisioner "local-exec" {
    when    = destroy
    command = self.input.aks_cli_destroy_command
  }
}

resource "terraform_data" "aks_nodepool_cli" {
  depends_on = [
    terraform_data.aks_cli
  ]

  for_each = local.extra_pool_map

  provisioner "local-exec" {
    command = join(" ", [
      "az",
      "aks",
      "nodepool",
      "add",
      "-g", var.resource_group_name,
      "--cluster-name", var.aks_cli_config.aks_name,
      "--nodepool-name", each.value.name,
      "--node-count", each.value.node_count,
      "--node-vm-size", each.value.vm_size,
      "--vm-set-type", each.value.vm_set_type,
      "--node-osdisk-type", each.value.os_disk_type,
      local.aks_custom_headers_flags,
      length(each.value.optional_parameters) == 0 ?
      "" :
      join(" ", [
        for param in each.value.optional_parameters :
        format("--%s %s", param.name, param.value)
      ]),
    ])
  }
}

# Grant AKS identity KMS-related Key Vault roles
resource "azurerm_role_assignment" "aks_identity_kms_roles" {
  for_each             = local.aks_kms_role_assignments
  scope                = each.value
  role_definition_name = each.key
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

data "azapi_resource" "aks" {
  count = var.aks_cli_config.disk_encryption_set_name != null && !var.aks_cli_config.dry_run ? 1 : 0

  depends_on = [terraform_data.aks_cli]

  type      = "Microsoft.ContainerService/managedClusters@2024-10-01"
  name      = var.aks_cli_config.aks_name
  parent_id = local.resource_group_id

  # Keep the payload small but sufficient for DES role assignments.
  response_export_values = [
    "identity",
    "properties.identityProfile",
  ]
}

locals {
  aks_identity_for_des = (var.aks_cli_config.disk_encryption_set_name != null && !var.aks_cli_config.dry_run) ? jsondecode(data.azapi_resource.aks[0].output) : null

  aks_kubelet_object_id = try(
    local.aks_identity_for_des.properties.identityProfile.kubeletidentity.objectId,
    local.aks_identity_for_des.properties.identityProfile.kubeletIdentity.objectId,
    null
  )

  aks_system_assigned_principal_id = try(local.aks_identity_for_des.identity.principalId, null)
}

# Grant Reader access to Disk Encryption Set for kubelet identity
resource "azurerm_role_assignment" "des_reader_kubelet" {
  count = var.aks_cli_config.disk_encryption_set_name != null && !var.aks_cli_config.dry_run ? 1 : 0

  scope                = local.disk_encryption_set_id
  role_definition_name = "Reader"
  principal_id         = local.aks_kubelet_object_id != null ? local.aks_kubelet_object_id : error("Unable to determine AKS kubelet identity objectId via azapi; cannot grant DES Reader role.")
}

# Grant Reader access to Disk Encryption Set for cluster identity
resource "azurerm_role_assignment" "des_reader_cluster" {
  count = var.aks_cli_config.disk_encryption_set_name != null && !var.aks_cli_config.dry_run ? 1 : 0

  scope                = local.disk_encryption_set_id
  role_definition_name = "Reader"
  principal_id = var.aks_cli_config.managed_identity_name != null ? azurerm_user_assigned_identity.userassignedidentity[0].principal_id : (
    local.aks_system_assigned_principal_id != null ? local.aks_system_assigned_principal_id : error("Unable to determine AKS system-assigned identity principalId via azapi; cannot grant DES Reader role.")
  )
}
