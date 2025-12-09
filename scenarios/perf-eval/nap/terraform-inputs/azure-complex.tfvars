# cluster configuration for Morgan Stanley
scenario_type  = "perf-eval"
scenario_name  = "nap"
deletion_delay = "4h"
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
            name     = "allow-egress"
            priority = 100
            action   = "Allow"
            rules = [
              {
                name             = "required-services"
                source_addresses = ["*"]
                target_fqdns = ["*.azure.com", "*.blob.core.windows.net", "*.data.mcr.microsoft.com",
                  "*.security.microsoft.com", "*.windows.net", "acs-mirror.azureedge.net",
                  "azure.archive.ubuntu.com",
                  "changelogs.ubuntu.com",
                  "login.microsoftonline.co",
                  "login.microsoftonline.com",
                  "management.azure.com",
                  "mcr-0001.mcr-msedge.net",
                  "mcr.microsoft.com",
                  "packages.aks.azure.com",
                  "packages.microsoft.com",
                  "security.ubuntu.com",
                "snapshot.ubuntu.com"]
                protocols = [
                  { port = "80", type = "Http" },
                  { port = "443", type = "Https" }
                ]
              },
              {
                name             = "k8s-updates"
                source_addresses = ["*"]
                target_fqdns = ["*.amazonaws.com", "*.cloudflarestorage.com",
                  "*.cloudfront.net", "*.docker.io",
                  "*.gcr.io",
                  "*.googleapis.com",
                  "*.googleusercontent.com",
                  "*.lz4.dev",
                  "*.pkg.dev",
                  "*.s3.amazonaws.com",
                  "*.s3.dualstack.ap-northeast-1.amazonaws.com",
                  "*.s3.dualstack.ap-southeast-1.amazonaws.com",
                  "*.s3.dualstack.eu-west-1.amazonaws.com",
                  "*.s3.dualstack.us-east-1.amazonaws.com",
                  "*.s3.dualstack.us-west-2.amazonaws.com",
                  "auth.docker.io",
                  "gcr.io",
                  "ghcr.io",
                  "k8s.gcr.io",
                  "pkg-containers.githubusercontent.com",
                  "registry-1.docker.io",
                  "registry.k8s.io",
                "storage.googleapis.com"]
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
    route_tables = [
      {
        name                          = "nap-rt"
        bgp_route_propagation_enabled = false
        routes = [
          {
            name                   = "default-route"
            address_prefix         = "0.0.0.0/0"
            next_hop_type          = "VirtualAppliance"
            next_hop_in_ip_address = "firewall:nap-firewall"
          },
          {
            name           = "firewall-internet"
            address_prefix = "publicip:firewall-pip"
            next_hop_type  = "Internet"
          }
        ]
        subnet_associations = [{ subnet_name = "nap-subnet-ms" }]
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
    aks_custom_headers    = [
      " OverrideControlplaneResources=W3siY29udGFpbmVyTmFtZSI6Imt1YmUtYXBpc2VydmVyIiwiY3B1TGltaXQiOiIzMCIsImNwdVJlcXVlc3QiOiIyNyIsIm1lbW9yeUxpbWl0IjoiNjRHaSIsIm1lbW9yeVJlcXVlc3QiOiI2NEdpIiwiZ29tYXhwcm9jcyI6MzB9XSAg,ControlPlaneUnderlay=hcp-underlay-canadacentral-cx-100,AKSHTTPCustomFeatures=OverrideControlplaneResources,EtcdServersOverrides=hyperscale"
    ]
    managed_identity_name = "nap-identity"
    kubernetes_version    = "1.33"
    api_server_subnet_name = "apiserver-subnet"
    default_node_pool = {
      name       = "system"
      node_count = 5
      vm_size    = "Standard_D8_v5"
    }
    kms_key_name              = "kms-nap"
    kms_key_vault_name        = "akskms"
    key_vault_network_access = "Private"
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
        name  = "outbound-type"
        value = "userDefinedRouting"
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