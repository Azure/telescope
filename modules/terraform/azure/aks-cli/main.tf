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
    "--no-ssh-key",
    local.kubernetes_version,
    local.optional_parameters,
    local.subnet_id_parameter,
    local.managed_identity_parameter,
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
  count                = var.aks_cli_config.managed_identity_name != null && var.subnet_id != null ? 1 : 0
  role_definition_name = "Network Contributor"
  scope                = var.subnet_id
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}


data "azurerm_subscription" "current" {}

#resource "azurerm_role_assignment" "rg_contributor" {
#  count                = !local.is_automatic_sku && var.aks_cli_config.managed_identity_name != null ? 1 : 0
#  role_definition_name = "Contributor"
#  scope                = "/subscriptions/${data.azurerm_subscription.current.subscription_id}/resourceGroups/${var.resource_group_name}"
#  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
#}

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
      az extension add -n aks-preview --version 18.0.0b10
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
    azurerm_role_assignment.network_contributor,
    #azurerm_role_assignment.rg_contributor
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

# Get the AKS cluster information after creation to access system-assigned identity
data "azurerm_kubernetes_cluster" "aks_cluster" {
  depends_on          = [terraform_data.aks_cli]
  name                = var.aks_cli_config.aks_name
  resource_group_name = var.resource_group_name
}

# For AKS Automatic, assign additional roles to the system-assigned managed identity
# resource "azurerm_role_assignment" "aks_automatic_contributor" {
#   count                = local.is_automatic_sku ? 1 : 0
#   role_definition_name = "Contributor"
#   scope                = "/subscriptions/${data.azurerm_subscription.current.subscription_id}/resourceGroups/${var.resource_group_name}"
#   principal_id         = data.azurerm_kubernetes_cluster.aks_cluster.identity[0].principal_id
#   depends_on           = [terraform_data.aks_cli]
# }

# resource "azurerm_role_assignment" "aks_automatic_network_contributor" {
#   count                = local.is_automatic_sku && var.subnet_id != null ? 1 : 0
#   role_definition_name = "Network Contributor"
#   scope                = var.subnet_id
#   principal_id         = data.azurerm_kubernetes_cluster.aks_cluster.identity[0].principal_id
#   depends_on           = [terraform_data.aks_cli]
# }

# Add Azure Kubernetes Service RBAC Cluster Admin role for kubectl access
# resource "azurerm_role_assignment" "aks_automatic_rbac_admin" {
#   count                = local.is_automatic_sku ? 1 : 0
#   role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
#   scope                = data.azurerm_kubernetes_cluster.aks_cluster.id
#   principal_id         = data.azurerm_kubernetes_cluster.aks_cluster.identity[0].principal_id
#   depends_on           = [terraform_data.aks_cli]
# }

# Get current client (user or service principal) running Terraform
data "azurerm_client_config" "current" {}

# Grant current user/service principal access to AKS cluster for kubectl operations
# resource "azurerm_role_assignment" "current_user_aks_admin" {
#   count                = local.is_automatic_sku ? 1 : 0
#   role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
#   scope                = data.azurerm_kubernetes_cluster.aks_cluster.id
#   principal_id         = data.azurerm_client_config.current.object_id
#   depends_on           = [terraform_data.aks_cli]
# }

resource "azurerm_role_assignment" "aks_automatic_contributor" {
  count                = local.is_automatic_sku ? 1 : 0
  role_definition_name = "Contributor"
  scope                = "/subscriptions/${data.azurerm_subscription.current.subscription_id}/resourceGroups/${var.resource_group_name}"
  principal_id         = data.azurerm_client_config.current.object_id
  depends_on           = [terraform_data.aks_cli]
}


resource "terraform_data" "aks_nodepool_cli" {
  depends_on = [
    terraform_data.aks_cli,
    #azurerm_role_assignment.aks_automatic_contributor,
    #azurerm_role_assignment.aks_automatic_network_contributor,
    #azurerm_role_assignment.aks_automatic_rbac_admin,
    azurerm_role_assignment.aks_automatic_contributor
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
