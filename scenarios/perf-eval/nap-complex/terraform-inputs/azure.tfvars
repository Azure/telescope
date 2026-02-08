# cluster configuration for Morgan Stanley
scenario_type  = "perf-eval"
scenario_name  = "nap-complex"
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
        name           = "AzureFirewallSubnet"
        address_prefix = "10.193.0.0/26"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

firewall_config_list = [
  {
    name                  = "nap-firewall"
    network_role          = "crud"
    sku_tier              = "Standard"
    subnet_name           = "AzureFirewallSubnet"
    public_ip_name        = "firewall-pip"
    threat_intel_mode     = "Alert"
    dns_proxy_enabled     = true
    ip_configuration_name = "nap-fw-ipconfig"
    application_rule_collections = [
      {
        name     = "allow-egress"
        priority = 100
        action   = "Allow"
        rules = [
          {
            name             = "required-services"
            source_addresses = ["*"]
            target_fqdns = ["*.azure.com", "*.azure.net",
              "*.windows.net", "*.azurecr.io", "*.ubuntu.com", "AzureKubernetesService",
              "mcr-0001.mcr-msedge.net", "*.microsoft.com",
              "*.microsoftonline.com", "*.microsoftonline.co", "*.azureedge.net",
              "packages.aks.azure.com", "mcr.microsoft.com",
              "*.azmk8s.io",
              "*.k8s.io",
              "mcr.microsoft.com",
              "*.mcr.microsoft.com",
              "*.data.mcr.microsoft.com",
              "*.azurecr.io",
              "*.blob.core.windows.net", "*.blob.storage.azure.net",
              "*.hcp.eastus2.azmk8s.io",
              "management.azure.com",
            "login.microsoftonline.com"]
            protocols = [
              { port = "80", type = "Http" },
              { port = "443", type = "Https" }
            ]
          }
    ]
    network_rule_collections = [
      {
        name     = "network-rules"
        priority = 100
        action   = "Allow"
        rules = [
          {
            name                  = "imds"
            source_addresses      = ["*"]
            destination_addresses = ["169.254.169.254"]
            destination_ports     = ["80"]
            protocols             = ["Any"]
          },
          {
            name                  = "dns"
            source_addresses      = ["*"]
            destination_addresses = ["*"]
            destination_ports     = ["53"]
            protocols             = ["UDP", "TCP"]
          },
          {
            name                  = "azure-and-web"
            source_addresses      = ["*"]
            destination_addresses = ["*"]
            destination_ports     = ["443"]
            protocols             = ["TCP", "UDP"]
          }
        ]
      }
    ]
  }
]
route_table_config_list = [
  {
    name                          = "nap-rt"
    bgp_route_propagation_enabled = false
    routes = [
      {
        name                   = "default-route"
        address_prefix         = "0.0.0.0/0"
        next_hop_type          = "VirtualAppliance"
        next_hop_firewall_name = "nap-firewall"
      },
      {
        name                         = "firewall-internet"
        address_prefix_publicip_name = "firewall-pip"
        next_hop_type                = "Internet"
      }
    ]
    subnet_associations = [{ subnet_name = "nap-subnet-ms" }]
  }
]

aks_cli_config_list = [
  {
    role                   = "nap"
    aks_name               = "nap-complex"
    sku_tier               = "standard"
    subnet_name            = "nap-subnet-ms"
    managed_identity_name  = "nap-identity"
    kubernetes_version     = "1.33"
    api_server_subnet_name = "apiserver-subnet"
    kms_config = {
      key_name       = "kms-nap"
      key_vault_name = "akskms"
      network_access = "Private"
    }
    default_node_pool = {
      name         = "system"
      os_disk_type = "Ephemeral"
      node_count   = 10
      vm_size      = "Standard_D16ds_v5"
    }
    extra_node_pool = [
      {
        name         = "prompool"
        node_count   = 1
        os_disk_type = "Ephemeral"
        vm_size      = "Standard_D16ds_v5"
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
        name  = "outbound-type"
        value = "userDefinedRouting"
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
      # TODO: enable private cluster + jumpbox , enable cilium once it is fixed
    ]
  }
]
