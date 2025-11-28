# cluster configuration for Morgan Stanley
scenario_type  = "perf-eval"
scenario_name  = "nap"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role               = "crud"
    vnet_name          = "nap-vnet-ms"
    vnet_address_space = "10.192.0.0/10"
    subnet = [
      {
        name           = "nap-subnet-ms"
        address_prefix = "10.192.0.0/11"
      },
      {
        name           = "jumpbox-subnet"
        address_prefix = "10.224.0.0/12"
      }
    ]
    network_security_group_name = "nsg-nap"
    nic_public_ip_associations  = []
    nsr_rules                   = [
      {
        name                       = "Allow-SSH"
        priority                   = 100
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "22"
        source_address_prefix      = "0.0.0.0/0"
        destination_address_prefix = "*"
      }
    ]
  }
]

aks_cli_config_list = [
  {
    role                  = "nap"
    aks_name              = "nap-complex"
    sku_tier              = "standard"
    subnet_name           = "nap-subnet-ms"
    managed_identity_name = "nap-identity"
    kubernetes_version    = "1.33"
    enable_private_cluster = true
    default_node_pool = {
      name       = "system"
      node_count = 5
      vm_size    = "Standard_D8_v5"
    }
    extra_node_pool = []
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
