# cluster configuration for Morgan Stanley
scenario_type  = "perf-eval"
scenario_name  = "nap"
deletion_delay = "2h"
owner          = "aks"

public_ip_config_list = [
  {
    name = "firewall-pip"
    count = 1
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
        address_prefix = "10.192.0.0/10"
      },
      {
        name           = "AzureFirewallSubnet"
        address_prefix = "10.193.0.0/26"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
    firewalls = [
      {
        name                  = "nap-firewall"
        sku_tier              = "Standard"
        subnet_name           = "AzureFirewallSubnet"
        public_ip_name        = "firewall-pip"
        threat_intel_mode     = "Alert"
        dns_proxy_enabled     = true
        ip_configuration_name = "nap-fw-ipconfig"
        application_rule_collections = [
          {
            name     = "egress-rules"
            priority = 100
            action   = "Allow"
            rules = [
              {
                name             = "azure-services"
                source_addresses = ["*"]
                target_fqdns     = ["*.azure.com", "*.core.windows.net", "*.azurecr.io", "AzureKubernetesService"]
                protocols = [
                  { port = "443", type = "Https" }
                ]
              },
              {
                name             = "linux-packages"
                source_addresses = ["*"]
                target_fqdns     = ["*.ubuntu.com", "archive.ubuntu.com", "security.ubuntu.com"]
                protocols = [
                  { port = "80", type = "Http" },
                  { port = "443", type = "Https" }
                ]
              }
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
                name                  = "dns"
                source_addresses      = ["*"]
                destination_addresses = ["*"]
                destination_ports     = ["53"]
                protocols             = ["UDP", "TCP"]
              },
              {
                name                  = "azure-api"
                source_addresses      = ["*"]
                destination_addresses = ["AzureCloud"]
                destination_ports     = ["443", "9000", "1194"]
                protocols             = ["TCP", "UDP"]
              },
              {
                name                  = "ntp"
                source_addresses      = ["*"]
                destination_addresses = ["*"]
                destination_ports     = ["123"]
                protocols             = ["UDP"]
              },
              {
                name                  = "http-https-outbound"
                source_addresses      = ["*"]
                destination_addresses = ["*"]
                destination_ports     = ["80", "443"]
                protocols             = ["TCP"]
              }
            ]
          }
        ]
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
      },
      {
        name  = "outbound-type"
        value = "userDefinedRouting"
      }
    ]
  }
]
