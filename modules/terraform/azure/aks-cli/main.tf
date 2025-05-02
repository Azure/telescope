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

  subnet_id_parameter = (var.subnet_id == null ?
    "" :
    format(
      "%s %s",
      "--vnet-subnet-id", var.subnet_id,
    )
  )

  managed_identity_parameter = (var.aks_cli_config.managed_identity_name == null ?
    "--enable-managed-identity" :
    format(
      "%s %s",
      "--assign-identity", azurerm_user_assigned_identity.userassignedidentity[0].id,
    )
  )
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
  scope                = var.subnet_id
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
      az extension add -n aks-preview --version 14.0.0b2
      az version
    EOT
    )
  }

  provisioner "local-exec" {
    when = destroy
    command = join(" ", [
      "az",
      "extension",
      "remove",
      "-n",
      "aks-preview",
    ])
  }
}

resource "terraform_data" "aks_cli" {
  depends_on = [
    terraform_data.enable_aks_cli_preview_extension,
    azurerm_role_assignment.network_contributor
  ]

  input = {
    group_name = var.resource_group_name,
    name       = var.aks_cli_config.aks_name
  }

  provisioner "local-exec" {
    command = join(" ", [
      "az",
      "aks",
      "create",
      "-g", self.input.group_name,
      "-n", self.input.name,
      "--location", var.location,
      "--tier", var.aks_cli_config.sku_tier,
      "--tags", join(" ", local.tags_list),
      local.aks_custom_headers_flags,
      "--no-ssh-key",
      local.kubernetes_version,
      "--nodepool-name", var.aks_cli_config.default_node_pool.name,
      "--node-count", var.aks_cli_config.default_node_pool.node_count,
      "--node-vm-size", var.aks_cli_config.default_node_pool.vm_size,
      "--vm-set-type", var.aks_cli_config.default_node_pool.vm_set_type,
      local.optional_parameters,
      local.subnet_id_parameter,
      local.managed_identity_parameter,
    ])
  }

  provisioner "local-exec" {
    when = destroy
    command = join(" ", [
      "az",
      "aks",
      "delete",
      "-g", self.input.group_name,
      "-n", self.input.name,
      "--yes",
    ])
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
