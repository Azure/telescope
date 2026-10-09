mock_provider "azurerm" {
  source = "./tests"

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000000"
      subscription_id = "12345678-1234-1234-1234-123456789012"
    }
  }
}

mock_provider "azapi" {}

run "qad_cluster_request" {
  command = plan

  variables {
    owner                           = "test"
    scenario_type                   = "perf-eval"
    scenario_name                   = "test-qad"
    network_config_list             = []
    aks_config_list                 = []
    aks_cli_config_list             = []
    azapi_config_list               = []
    public_ip_config_list           = []
    dns_zones                       = []
    disk_encryption_set_config_list = []
    key_vault_config_list           = []
    qad_config_list = [
      {
        role               = "client"
        aks_name           = "test-qad"
        dns_prefix         = "test-qad"
        api_version        = "2026-07-02-preview"
        kubernetes_version = "1.37.0"
        system_node_pool = {
          name    = "systempool"
          count   = 3
          vm_size = "Standard_D2s_v3"
        }
        user_node_pools = [
          {
            name        = "user"
            count       = 40
            vm_size     = "Standard_D16s_v3"
            node_labels = { csi = "true" }
          }
        ]
        dry_run = true
      }
    ]
    json_input = {
      region = "eastus2euap"
      run_id = "test123"
    }
  }

  assert {
    condition     = endswith(module.qad["client"].request_url, "api-version=2026-07-02-preview")
    error_message = "QAD cluster request must use API version 2026-07-02-preview."
  }

  assert {
    condition     = contains(module.qad["client"].request_headers, "EnableQuickAttachDetach=true")
    error_message = "QAD cluster request must include the EnableQuickAttachDetach=true header."
  }

  assert {
    condition     = module.qad["client"].request_body.properties.kubernetesVersion == "1.37.0"
    error_message = "QAD cluster must use Kubernetes version 1.37.0."
  }

  assert {
    condition     = module.qad["client"].request_body.properties.storageProfile.diskCSIDriver.enabled
    error_message = "QAD cluster must enable the disk CSI driver."
  }

  assert {
    condition     = module.qad["client"].request_body.properties.oidcIssuerProfile.enabled
    error_message = "QAD cluster must enable the OIDC issuer."
  }

  assert {
    condition = (
      module.qad["client"].request_body.properties.agentPoolProfiles[1].count == 40 &&
      module.qad["client"].request_body.properties.agentPoolProfiles[1].vmSize == "Standard_D16s_v3" &&
      module.qad["client"].request_body.properties.agentPoolProfiles[1].nodeLabels.csi == "true"
    )
    error_message = "QAD user pool must contain 40 Standard_D16s_v3 nodes labeled csi=true."
  }
}

run "qad_disabled_by_default" {
  command = plan

  variables {
    owner                           = "test"
    scenario_type                   = "perf-eval"
    scenario_name                   = "test-qad"
    network_config_list             = []
    aks_config_list                 = []
    aks_cli_config_list             = []
    azapi_config_list               = []
    qad_config_list                 = []
    public_ip_config_list           = []
    dns_zones                       = []
    disk_encryption_set_config_list = []
    key_vault_config_list           = []
    json_input = {
      region = "eastus"
      run_id = "test123"
    }
  }

  assert {
    condition     = length(local.qad_config_map) == 0
    error_message = "QAD provisioning must be disabled when no QAD configuration is supplied."
  }
}
