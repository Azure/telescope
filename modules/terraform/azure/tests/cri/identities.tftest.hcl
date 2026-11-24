# Run with -test-directory=tests/cri and an Azure Resource Consumer -var-file.
mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id = "00000000-0000-0000-0000-000000000001"
      object_id = "00000000-0000-0000-0000-000000000002"
    }
  }
}
mock_provider "azapi" {}

variables {
  json_input = {
    run_id = "123456789"
    region = "eastus"
    cri_identities = {
      control_plane = {
        id           = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/telescope-controlplane-MI"
        principal_id = "00000000-0000-0000-0000-000000000003"
      }
      kubelet = {
        id        = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/cri-kubelet"
        client_id = "00000000-0000-0000-0000-000000000004"
        object_id = "00000000-0000-0000-0000-000000000005"
      }
    }
  }
}

run "client_uses_preconfigured_identities" {
  command = plan

  assert {
    condition = contains(keys(module.aks), "client") ? (
      module.aks["client"].aks_cluster.identity[0].type == "UserAssigned" &&
      contains(module.aks["client"].aks_cluster.identity[0].identity_ids, var.json_input.cri_identities.control_plane.id) &&
      module.aks["client"].aks_cluster.kubelet_identity[0].user_assigned_identity_id == var.json_input.cri_identities.kubelet.id &&
      module.aks["client"].aks_cluster.kubelet_identity[0].object_id == var.json_input.cri_identities.kubelet.object_id &&
      module.aks["client"].aks_cluster.kubelet_identity[0].client_id == var.json_input.cri_identities.kubelet.client_id
      ) : (
      contains(module.aks-cli["client"].aks_cli_identity_arguments, "--assign-identity '${var.json_input.cri_identities.control_plane.id}'") &&
      contains(module.aks-cli["client"].aks_cli_identity_arguments, "--assign-kubelet-identity '${var.json_input.cri_identities.kubelet.id}'")
    )
    error_message = "The client cluster must use both configured managed identities."
  }
}
