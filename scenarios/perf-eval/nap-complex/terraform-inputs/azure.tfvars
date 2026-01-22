# cluster configuration for Morgan Stanley
scenario_type  = "perf-eval"
scenario_name  = "nap-complex"
deletion_delay = "2h"
owner          = "aks"

public_ip_config_list = [
  {
    name  = "firewall-pip"
    count = 1
  },
  {
    name  = "jumpbox-pip"
    count = 1
  }
]

key_vault_config_list = [
  {
    name = "akskms"
    keys = [
      {
        key_name = "kms-nap"
      }
    ]
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
      }
    ]
    network_security_group_name = "test"
    nic_public_ip_associations  = [
      {
        nic_name              = "jumpbox-nic"
        subnet_name           = "jumpbox-subnet"
        ip_configuration_name = "jumpbox-ipconfig"
        public_ip_name        = "jumpbox-pip"
      }
    ]
    nsr_rules = [
      {
        name                       = "AllowSSH"
        priority                   = 100
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "22"
        source_address_prefix      = "*"
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
    api_server_subnet_name = "apiserver-subnet"
    kms_config = {
      key_name       = "kms-nap"
      key_vault_name = "akskms"
      network_access = "Private"
    }
    default_node_pool = {
      name       = "system"
      node_count = 10
      vm_size    = "Standard_D16s_v5"
    }
    extra_node_pool = [
      {
        name       = "prompool"
        node_count = 1
        vm_size    = "Standard_D16_v5"
        optional_parameters = [
          {
            name  = "labels"
            value = "prometheus=true"
          }
        ]
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
      }
      # TODO: enable private cluster after bug fix for hyperscale has been rolled out
      # {
      #   name  = "enable-private-cluster"
      #   value = ""
      # }
    ]
  }
]

vm_config_list = [
  {
    role     = "nap"
    name     = "my-jumpbox"
    vm_size  = "Standard_D4s_v3"
    nic_name = "jumpbox-nic"
    aks_name = "nap-complex"
    nsg = {
      enabled = true
      rules = [
        {
          name                   = "AllowSSH"
          priority               = 100
          destination_port_range = "22"
        }
      ]
    }
    vm_tags = {
      jumpbox = "true"
    }
  }
]
