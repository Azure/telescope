# Azure AKS with Key Vault KMS Encryption Example Configuration
# This configuration demonstrates how to set up AKS with ETCD encryption using Azure Key Vault

# Key Vault KMS Configuration
# When specified, a Key Vault is created with encryption keys
# Each AKS cluster must specify which key to use via kms_key_name
key_vault_kms_config = {
  name = "akskms" # Must be globally unique (3-24 chars)
  keys = [
    {
      key_name                 = "kms-prod"
    },
    {
      key_name                 = "kms-dev"
    }
  ]
}

# Network Configuration
network_config_list = [
  {
    role               = "server"
    vnet_name          = "aks-vnet"
    vnet_address_space = "172.16.0.0/16"
    subnet = [
      {
        name           = "aks-subnet"
        address_prefix = "172.16.1.0/24"
      }
    ]
    network_security_group_name = "aks-nsg"
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

# AKS Configuration with KMS Encryption (using Terraform provider)
aks_config_list = [
  {
    role       = "cas"
    aks_name   = "cas"
    dns_prefix = "cas"
    sku_tier   = "Standard"
    network_profile = {
      network_plugin = "azure"
      network_policy = "azure"
      service_cidr   = "172.20.0.0/16"
      dns_service_ip = "172.20.0.10"
    }
    default_node_pool = {
      name                         = "system"
      node_count                   = 2
      auto_scaling_enabled         = false
      vm_size                      = "Standard_D2_v5"
      os_disk_type                 = "Managed"
      only_critical_addons_enabled = false
      temporary_name_for_rotation  = "defaulttmp"
    }
    extra_node_pool = [
      {
        name                 = "userpool"
        node_count           = 1
        min_count            = 1
        max_count            = 3
        auto_scaling_enabled = true
        vm_size              = "Standard_D2_v5"
        max_pods             = 110
        node_labels          = { "cas" = "dedicated" }
      }
    ]
    oidc_issuer_enabled       = false
    workload_identity_enabled = false
    # Optional: Specify which key this AKS cluster should use
    # If not specified, uses the first key
    kms_key_name = "kms-prod"
    key_vault_network_access = "Public"
  }
]


# AKS Configuration with KMS Encryption (using Azure CLI)
# Mirrors the aks_config_list structure but uses CLI for deployment
#aks_cli_config_list = [
#  {
#    role                          = "server"
#    aks_name                      = "aks-kms-cluster-cli"
#    sku_tier                      = "Standard"
#    subnet_name                   = "aks-subnet"
#    managed_identity_name         = "kms-test"
#    use_aks_preview_cli_extension = true
#    network_profile = {
#     network_plugin = "azure"
#      network_policy = "azure"
#      service_cidr   = "172.21.0.0/16"
#      dns_service_ip = "172.21.0.10"
#    }
#    default_node_pool = {
#      name        = "system"
#      node_count  = 5
#      vm_size     = "Standard_D4_v5"
#      vm_set_type = "VirtualMachineScaleSets"
#    }
#    extra_node_pool = [
#      {
#        name        = "userpool"
#        node_count  = 1
#        vm_size     = "Standard_D4_v5"
#        vm_set_type = "VirtualMachineScaleSets"
#      }
#    ]
#    # Optional: Specify which key this AKS cluster should use
#    # If not specified, uses the first key
#    kms_key_name              = "kms-dev"
#    key_vault_network_access = "Public"
#    oidc_issuer_enabled       = true
#    workload_identity_enabled = true
#  }
#]
