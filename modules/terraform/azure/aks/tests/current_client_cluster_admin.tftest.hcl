mock_provider "azurerm" {
  mock_resource "azurerm_kubernetes_cluster" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/test-rg/providers/Microsoft.ContainerService/managedClusters/test-aks"
    }
  }

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id = "00000000-0000-0000-0000-000000000000"
      object_id = "12345678-1234-5678-9abc-def012345678"
    }
  }
}

mock_provider "local" {}

variables {
  resource_group_name = "test-rg"
  location            = "swedencentral"
  tags                = {}
  aks_aad_enabled     = true
  aks_config = {
    role       = "cas"
    aks_name   = "test-aks"
    dns_prefix = "testaks"
    sku_tier   = "Standard"
    network_profile = {
      network_plugin      = "azure"
      network_plugin_mode = "overlay"
    }
    default_node_pool = {
      name                         = "system"
      node_count                   = 5
      vm_size                      = "Standard_D8s_v5"
      only_critical_addons_enabled = true
      temporary_name_for_rotation  = "systemtmp"
    }
    extra_node_pool = []
  }
}

run "disabled_by_default" {
  command = plan

  assert {
    condition     = length(azurerm_role_assignment.current_client_cluster_admin) == 0
    error_message = "Existing scenarios must not receive new role assignments by default."
  }
}

run "grants_only_current_cluster_access" {
  command = apply

  variables {
    aks_config = merge(var.aks_config, {
      grant_current_client_cluster_admin = true
    })
  }

  assert {
    condition     = length(azurerm_role_assignment.current_client_cluster_admin) == 1
    error_message = "Opting in must create exactly one assignment."
  }

  assert {
    condition     = azurerm_role_assignment.current_client_cluster_admin[0].scope == azurerm_kubernetes_cluster.aks.id
    error_message = "Access must be scoped to this cluster, not its subscription or resource group."
  }

  assert {
    condition     = azurerm_role_assignment.current_client_cluster_admin[0].principal_id == "12345678-1234-5678-9abc-def012345678"
    error_message = "Access must be granted to the Terraform identity."
  }

  assert {
    condition     = azurerm_role_assignment.current_client_cluster_admin[0].role_definition_name == "Azure Kubernetes Service RBAC Cluster Admin"
    error_message = "The test identity requires Kubernetes cluster-admin access."
  }

  assert {
    condition     = azurerm_kubernetes_cluster.aks.azure_active_directory_role_based_access_control[0].azure_rbac_enabled
    error_message = "The cluster role assignment requires Entra integration with Azure RBAC."
  }
}

run "rejects_assignment_without_entra" {
  command = plan

  variables {
    aks_aad_enabled = false
    aks_config = merge(var.aks_config, {
      grant_current_client_cluster_admin = true
    })
  }

  expect_failures = [azurerm_role_assignment.current_client_cluster_admin]
}
