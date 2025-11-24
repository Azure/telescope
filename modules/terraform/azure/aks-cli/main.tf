locals {
  tags_list = [
    for key, value in merge(var.tags, { "role" = var.aks_cli_config.role }) :
    format("%s=%s", key, value)
  ]

  extra_pool_map = {
    for pool in var.aks_cli_config.extra_node_pool :
    pool.name => pool
  }

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
    var.key_management_service == null ?
    "" :
    join(" ", [
      "--enable-azure-keyvault-kms",
      format("--azure-keyvault-kms-key-id %s", var.key_management_service.key_vault_key_id),
      format("--azure-keyvault-kms-key-vault-network-access %s", var.aks_cli_config.key_vault_network_access)
    ])
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


  api_server_vnet_integration_parameter = (var.aks_cli_config.enable_apiserver_vnet_integration && local.api_server_subnet_id != null ?
    format(
      "--enable-apiserver-vnet-integration --apiserver-subnet-id %s",
      local.api_server_subnet_id,
    ) :
    ""
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
      "--vm-set-type", var.aks_cli_config.default_node_pool.vm_set_type
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
    local.optional_parameters,
    local.kms_parameters,
    local.subnet_id_parameter,
    local.managed_identity_parameter,
    local.api_server_vnet_integration_parameter,
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

resource "azurerm_user_assigned_identity" "userassignedidentity" {
  count               = var.aks_cli_config.managed_identity_name == null ? 0 : 1
  location            = var.location
  name                = var.aks_cli_config.managed_identity_name
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "network_contributor" {
  count                = var.aks_cli_config.managed_identity_name == null ? 0 : 1
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
    azurerm_role_assignment.aks_key_service_encryption_user,
    azurerm_role_assignment.aks_kv_service_encryption_user
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

# Grant Key Vault Crypto Service Encryption User role for KMS encryption
#resource "azurerm_role_assignment" "aks_key_service_encryption_user" {
#  count                = var.key_management_service == null ? 0 : 1
#  scope                = var.key_management_service.key_vault_key_id
#  role_definition_name = "Key Vault Crypto Service Encryption User"
# principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
#}
resource "azurerm_role_assignment" "aks_kv_service_encryption_user" {
  count                = var.key_management_service == null ? 0 : 1
  scope                = var.key_management_service.key_vault_id
  role_definition_name = "Key Vault Crypto Service Encryption User"
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}