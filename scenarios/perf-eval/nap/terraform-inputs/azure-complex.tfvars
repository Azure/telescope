# cluster configuration for Morgan Stanley
scenario_type  = "perf-eval"
scenario_name  = "nap"
deletion_delay = "2h"
owner          = "aks"

public_ip_config_list = [
  {
    name  = "firewall-pip"
    count = 1
  }
]

key_vault_config_list = [
  {
    name = "akskms"
    keys = [
      {
        key_name = "kms-nap"
      },
      {
        key_name = "disk-encryption-key"
      }
    ]
  }
]

# Disk Encryption Set for OS disk encryption with Customer-Managed Keys
# Reference: https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys
disk_encryption_set_config_list = [
  {
    name                      = "nap-disk-encryption-set"
    key_vault_name            = "akskms"
    key_name                  = "disk-encryption-key"
    encryption_type           = "EncryptionAtRestWithCustomerKey"
    auto_key_rotation_enabled = false
  }
]

network_config_list = [
  {
    role               = "crud"
    vnet_name          = "nap-vnet-ms"
    vnet_address_space = "10.192.0.0/10"
    subnet = [
      {
        name           = "nap-subnet-ms"
        address_prefix = "10.192.0.0/16"
      },
      {
        name           = "apiserver-subnet"
        address_prefix = "10.240.0.0/16"
      },
      {
        name           = "jumpbox-subnet"
        address_prefix = "10.224.0.0/12"
      },
      {
        name           = "AzureFirewallSubnet"
        address_prefix = "10.193.0.0/26"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]
aks_cli_config_list = [
  {
    role                     = "nap"
    aks_name                 = "nap-complex"
    sku_tier                 = "standard"
    subnet_name              = "nap-subnet-ms"
    managed_identity_name    = "nap-identity"
    kubernetes_version       = "1.33"
    api_server_subnet_name   = "apiserver-subnet"
    kms_key_name             = "kms-nap"
    kms_key_vault_name       = "akskms"
    key_vault_network_access = "Private"
    disk_encryption_set_name = "nap-disk-encryption-set"
    node_osdisk_type         = "Ephemeral"
    default_node_pool = {
      name       = "system"
      node_count = 10
      vm_size    = "Standard_D16ds_v4"
    }
    extra_node_pool = [
      {
        name       = "prompool"
        node_count = 5
        vm_size    = "Standard_D16ds_v4"
      }
    ]
    optional_parameters = [
      {
        name  = "node-provisioning-mode"
        value = "Auto"
      },
      {
        name  = "network-plugin"
        value = "azure"
      },
      {
        name  = "network-plugin-mode"
        value = "overlay"
      },
      {
        name  = "node-init-taints"
        value = "CriticalAddonsOnly=true:NoSchedule"
      },
      {
        name  = "pod-cidr"
        value = "10.128.0.0/11"
      },
      {
        name  = "enable-oidc-issuer"
        value = ""
      },
      {
        name  = "enable-workload-identity"
        value = ""
      },
      {
        name  = "enable-addons"
        value = "azure-keyvault-secrets-provider"
      },
      {
        name  = "enable-keda"
        value = ""
      },
      {
        name  = "enable-image-cleaner"
        value = ""
      },
      {
        name  = "network-dataplane"
        value = "cilium"
      },
      {
        name  = "network-policy"
        value = "cilium"
      },
      # TODO: enable private cluster after bug fix for hyperscale has been rolled out
      {
        name  = "enable-private-cluster"
        value = ""
      }
    ]
  }
]

# Jumpbox Configuration - Auto-provisioned for testing
jumpbox_config_list = [
  {
    role        = "nap"
    name        = "nap-jumpbox"
    subnet_name = "jumpbox-subnet"
    vm_size     = "Standard_D4s_v3"
    aks_name    = "nap-complex"
  }
]
