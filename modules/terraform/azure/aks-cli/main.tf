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

resource "terraform_data" "aks_cli_preview" {
  count = var.aks_cli_config.use_aks_preview_cli_extension == true ? 1 : 0

  provisioner "local-exec" {
    command = join(" ", [
      "az",
      "extension",
      "add",
      "-n",
      "aks-preview",
    ])
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
    terraform_data.aks_cli_preview,
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
      length(var.aks_cli_config.default_node_pool.node_labels) == 0 ? "" : format("%s %s",
        "--labels", join(" ", [
          for label_name, label_value in var.aks_cli_config.default_node_pool.node_labels :
          format("%s=%s", label_name, label_value)
        ])
      ),
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
      local.aks_custom_headers_flags,
      length(each.value.node_labels) == 0 ? "" : format("%s %s",
        "--labels", join(" ", [
          for label_name, label_value in each.value.node_labels :
          format("%s=%s", label_name, label_value)
        ])
      ),
      "--vm-set-type", each.value.vm_set_type,
    ])
  }
}
