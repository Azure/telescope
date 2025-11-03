scenario_type  = "perf-eval"
scenario_name  = "pod-diff-node-same-zone"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role               = "pod2pod"
    vnet_name          = "pod2pod-vnet"
    vnet_address_space = "10.30.0.0/16"
    subnet = [
      {
        name           = "pod2pod-subnet-1"
        address_prefix = "10.30.1.0/24"
      }
    ]
    network_security_group_name = "same-nsg"
    nic_public_ip_associations  = []
    nsr_rules = [
      {
        name                       = "Allow-Port-5201"
        priority                   = 120
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "5201"
        source_address_prefix      = "0.0.0.0/0"
        destination_address_prefix = "*"
      },
      {
        name                       = "Allow-Port-20000"
        priority                   = 121
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "20000"
        source_address_prefix      = "0.0.0.0/0"
        destination_address_prefix = "*"
      },
      {
        name                       = "Allow-Port-20003"
        priority                   = 122
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "20003"
        source_address_prefix      = "0.0.0.0/0"
        destination_address_prefix = "*"
      },
      {
        name                       = "Allow-Port-20005"
        priority                   = 123
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "20005"
        source_address_prefix      = "0.0.0.0/0"
        destination_address_prefix = "*"
      },
      {
        name                       = "Allow-Port-80"
        priority                   = 124
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "80"
        source_address_prefix      = "0.0.0.0/0"
        destination_address_prefix = "*"
      },
      {
        name                       = "Allow-API-Server"
        priority                   = 125
        direction                  = "Outbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      },
      {
        name                       = "Allow-WebSocket"
        priority                   = 126
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "443"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  }
]

aks_cli_config_list = [
  {
    role               = "pod2pod"
    aks_name           = "pod-diff-node"
    sku_tier           = "standard"
    kubernetes_version = "1.32"
    subnet_name        = "pod2pod-subnet-1"
    default_node_pool = {
      name       = "default"
      node_count = 1
      vm_size    = "Standard_D16s_v5"
    }
    extra_node_pool = [
      {
        name       = "client",
        node_count = 1,
        vm_size    = "Standard_D16s_v5",
        optional_parameters = [
          {
            name  = "os-sku"
            value = "Ubuntu2404"
          },
          {
            name  = "labels"
            value = "client=true test=true"
          },
          {
            name  = "node-taints",
            value = "dedicated-test=true:NoSchedule,dedicated-test=true:NoExecute"
          },
          {
            name  = "zones",
            value = "2"
          }
        ]
      },
      {
        name       = "server",
        node_count = 1,
        vm_size    = "Standard_D16s_v5",
        optional_parameters = [
          {
            name  = "os-sku"
            value = "Ubuntu2404"
          },
          {
            name  = "labels"
            value = "server=true test=true"
          },
          {
            name  = "node-taints",
            value = "dedicated-test=true:NoSchedule,dedicated-test=true:NoExecute"
          },
          {
            name  = "zones",
            value = "2"
          }
        ]
      },
    ]
    optional_parameters = [
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
        value = "10.128.0.0/9"
      },
      {
        name  = "service-cidr"
        value = "192.168.0.0/16"
      },
      {
        name  = "dns-service-ip"
        value = "192.168.0.10"
      },
      {
        name  = "os-sku"
        value = "Ubuntu2404"
      }
    ]
  }
]