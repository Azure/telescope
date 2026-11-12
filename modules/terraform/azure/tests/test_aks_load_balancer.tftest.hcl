mock_provider "azurerm" {}

mock_provider "azapi" {}

variables {
  json_input = {
    run_id = "load-balancer-test"
    region = "eastus"
  }

  aks_config_list = [
    {
      role       = "test"
      aks_name   = "test"
      dns_prefix = "test"
      sku_tier   = "Standard"
      network_profile = {
        network_plugin      = "azure"
        network_plugin_mode = "overlay"
      }
      default_node_pool = {
        name                         = "default"
        node_count                   = 3
        vm_size                      = "Standard_D4ds_v5"
        os_disk_type                 = "Managed"
        only_critical_addons_enabled = true
        temporary_name_for_rotation  = "defaulttmp"
      }
      extra_node_pool = []
    }
  ]
}

run "valid_without_load_balancer_profile" {
  command = plan
}

run "valid_explicit_load_balancer_profile" {
  command = plan

  variables {
    aks_config_list = [
      {
        role       = "test"
        aks_name   = "test"
        dns_prefix = "test"
        sku_tier   = "Standard"
        network_profile = {
          network_plugin      = "azure"
          network_plugin_mode = "overlay"
          outbound_type       = "loadBalancer"
          load_balancer_profile = {
            managed_outbound_ip_count = 12
            outbound_ports_allocated  = 1024
          }
        }
        default_node_pool = {
          name                         = "default"
          node_count                   = 3
          vm_size                      = "Standard_D4ds_v5"
          os_disk_type                 = "Managed"
          only_critical_addons_enabled = true
          temporary_name_for_rotation  = "defaulttmp"
        }
        extra_node_pool = []
      }
    ]
  }

  assert {
    condition = (
      module.aks["test"].aks_cluster.network_profile[0].load_balancer_profile[0].managed_outbound_ip_count == var.aks_config_list[0].network_profile.load_balancer_profile.managed_outbound_ip_count &&
      module.aks["test"].aks_cluster.network_profile[0].load_balancer_profile[0].outbound_ports_allocated == var.aks_config_list[0].network_profile.load_balancer_profile.outbound_ports_allocated
    )
    error_message = "The AKS resource must preserve the explicitly configured outbound IP count and SNAT ports."
  }
}
