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

  role_assignments = var.aks_cli_config.grant_rbac_permissions ? {
    aks_contributor = {
      scope                = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}"
      role_definition_name = "Contributor"
      principal_id         = data.azurerm_client_config.current.object_id
      role_name            = "AKS Contributor"
    }
    aks_cluster_admin = {
      scope                = var.aks_cli_config.grant_rbac_permissions ? data.azurerm_kubernetes_cluster.aks[0].id : ""
      role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
      principal_id         = data.azurerm_client_config.current.object_id
      role_name            = "AKS Cluster Admin"
    }
  } : {}

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
    azurerm_role_assignment.network_contributor
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

# Get current client configuration to obtain object ID for RBAC assignments
data "azurerm_client_config" "current" {}

# Get the AKS cluster information for RBAC assignments
data "azurerm_kubernetes_cluster" "aks" {
  count               = var.aks_cli_config.grant_rbac_permissions ? 1 : 0
  name                = var.aks_cli_config.aks_name
  resource_group_name = var.resource_group_name

  depends_on = [
    terraform_data.aks_cli
  ]
}

# Grant RBAC permissions for AKS access
resource "terraform_data" "role_assignment" {
  for_each = local.role_assignments

  input = {
    scope                = each.value.scope
    role_definition_name = each.value.role_definition_name
    principal_id         = each.value.principal_id
    role_name            = each.value.role_name
  }

  provisioner "local-exec" {
    command = <<-EOT
      # Check if role assignment already exists
      existing_role=$(az role assignment list \
        --scope "${self.input.scope}" \
        --role "${self.input.role_definition_name}" \
        --assignee "${self.input.principal_id}" \
        --query "length(@)" -o tsv 2>/dev/null || echo "0")
      
      if [ "$existing_role" -eq 0 ]; then
        echo "Creating ${self.input.role_name} role assignment..."
        az role assignment create \
          --scope "${self.input.scope}" \
          --role "${self.input.role_definition_name}" \
          --assignee "${self.input.principal_id}"
      else
        echo "${self.input.role_name} role assignment already exists, skipping creation..."
      fi
      
      # Wait for role assignment propagation (hardcoded 30 attempts = 5 minutes)
      max_attempts=30
      role_name="${self.input.role_name}"
      attempt=1
      
      echo "Waiting for $role_name role assignment to propagate..."
      while [ $attempt -le $max_attempts ]; do
        echo "Checking $role_name role propagation (attempt $attempt/$max_attempts)..."
        
        # Check if role assignment is active and propagated
        active_role=$(az role assignment list \
          --scope "${self.input.scope}" \
          --role "${self.input.role_definition_name}" \
          --assignee "${self.input.principal_id}" \
          --include-inherited \
          --query "length(@)" -o tsv 2>/dev/null || echo "0")
        
        if [ "$active_role" -gt 0 ]; then
          echo "$role_name role assignment has propagated successfully."
          exit 0
        fi
        
        if [ $attempt -eq $max_attempts ]; then
          echo "Error: $role_name role assignment has not propagated after 5 minutes."
          exit 1
        fi
        
        echo "Role assignment not yet propagated, waiting 10 seconds..."
        sleep 10
        attempt=$((attempt + 1))
      done
    EOT
  }

  depends_on = [
    terraform_data.aks_cli,
    data.azurerm_kubernetes_cluster.aks
  ]
}
