mock_provider "azurerm" {
  source = "./tests"

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000000"
      subscription_id = "12345678-1234-1234-1234-123456789012"
    }
  }
}

# Test case 1: Verify AKS config works without disk_encryption_set_name (null case)
run "aks_without_disk_encryption" {
  command = plan

  variables {
    owner               = "test"
    scenario_type       = "perf-eval"
    scenario_name       = "test"
    network_config_list = []
    aks_config_list = [
      {
        role       = "test"
        aks_name   = "test-aks"
        dns_prefix = "testaks"
        sku_tier   = "Standard"
        network_profile = {
          network_plugin = "azure"
        }
        default_node_pool = {
          name                         = "default"
          node_count                   = 1
          vm_size                      = "Standard_D2s_v3"
          os_disk_type                 = "Managed"
          only_critical_addons_enabled = false
          temporary_name_for_rotation  = "defaulttmp"
        }
        extra_node_pool = []
      }
    ]
    aks_cli_config_list             = []
    public_ip_config_list           = []
    dns_zones                       = []
    disk_encryption_set_config_list = []
    key_vault_config_list           = []
    json_input = {
      region = "East US"
      run_id = "test123"
    }
    deletion_delay = "720h"
  }

  assert {
    condition     = local.updated_aks_config_list[0].disk_encryption_set_name == null
    error_message = "disk_encryption_set_name should be null when not specified"
  }
}

# Test case 2: Verify AKS CLI config works without disk_encryption_set_name (null case)
run "aks_cli_without_disk_encryption" {
  command = plan

  variables {
    owner               = "test"
    scenario_type       = "perf-eval"
    scenario_name       = "test"
    network_config_list = []
    aks_config_list     = []
    aks_cli_config_list = [
      {
        role     = "test-cli"
        aks_name = "test-aks-cli"
        sku_tier = "Standard"
        default_node_pool = {
          name       = "system"
          node_count = 2
          vm_size    = "Standard_D2s_v3"
        }
        extra_node_pool = []
        dry_run         = true
      }
    ]
    public_ip_config_list           = []
    dns_zones                       = []
    disk_encryption_set_config_list = []
    key_vault_config_list           = []
    json_input = {
      region = "East US"
      run_id = "test123"
    }
    deletion_delay = "720h"
  }

  assert {
    condition     = local.updated_aks_cli_config_list[0].disk_encryption_set_name == null
    error_message = "disk_encryption_set_name should be null when not specified in AKS CLI config"
  }
}
