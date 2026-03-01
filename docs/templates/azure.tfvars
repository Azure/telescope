# Azure Terraform Variables Template
# This template helps with onboarding new test scenarios for Azure infrastructure
# Replace all <template-values> with your specific configuration

# ==============================================================================
# PIPELINE INTEGRATION AND DATA FLOW
# ==============================================================================

# IMPORTANT: Understanding json_input Parameter Flow
# The json_input object below receives its values from the Azure DevOps pipeline through this flow:
#
# 1. Pipeline Definition (docs/templates/pipeline.yml):
#    - Stage parameters: cloud, regions, matrix values
#    - Matrix parameters: Custom key-value pairs for test variations
#
# 2. Terraform Input Variables Step (steps/terraform/set-input-variables-azure.yml):
#    - Collects pipeline stage parameters (run_id, region, etc.)
#    - Merges pipeline matrix parameters to override specific values
#    - Constructs the json_input object
#    - Passes it to terraform as TF_VAR_json_input
#
# 3. This tfvars file:
#    - Uses json_input values to configure Azure resources
#    - Allows matrix-based variations for multiple test jobs
#    - Enables running same infrastructure with different configurations
#
# Pipeline Matrix Examples:
# matrix:
#   small_cluster:
#     k8s_machine_type: "Standard_D2s_v3"
#     aks_kubernetes_version: "1.28"
#   large_cluster:
#     k8s_machine_type: "Standard_D8s_v3" 
#     aks_kubernetes_version: "1.29"
#
# This creates multiple jobs with the same tfvars but different json_input values.

# ==============================================================================
# BASIC CONFIGURATION
# ==============================================================================

# JSON input configuration - main input object containing scenario details
# NOTE: These values are automatically populated by the pipeline - do not set manually
json_input = {
  # Pipeline-provided values (from pipeline stage parameters):
  run_id                 = "<run-id>"                       # Auto-generated from pipeline run (e.g., "test-run-001", "perf-001")
  region                 = "<azure-region>"                 # From pipeline regions parameter - Available: eastus, eastus2, westus, westus2, centralus, northcentralus, southcentralus, westcentralus, eastasia, southeastasia, japaneast, japanwest, australiaeast, australiasoutheast, brazilsouth, canadacentral, canadaeast, northeurope, westeurope, uksouth, ukwest, francecentral, germanywestcentral, norwayeast, switzerlandnorth, uaenorth, southafricanorth, centralindia, southindia, westindia, koreacentral, koreasouth
  
  # Matrix-overridable values (can be customized per test job via pipeline matrix):
  aks_sku_tier           = "<sku-tier>"                     # From matrix or default - Options: "Free", "Standard", "Premium"
  aks_kubernetes_version = "<k8s-version>"                  # From matrix or default - e.g., "1.28", "1.29", "1.30", "1.31". Use null to use cluster default
  aks_network_policy     = "<network-policy>"              # From matrix or default - Options: "azure", "cilium", null. If "azure" or "cilium", aks_network_dataplane must match or be null
  aks_network_dataplane  = "<network-dataplane>"           # From matrix or default - Options: "azure", "cilium", null. Must match network_policy if specified
  aks_custom_headers     = [<custom-headers>]               # From matrix or default - List of strings, e.g., ["header1", "header2"] or []
  k8s_machine_type       = "<vm-size>"                      # From matrix or default - e.g., "Standard_D2s_v3", "Standard_D4s_v3", "Standard_D8s_v3", "Standard_D16s_v3", null to use defaults
  k8s_os_disk_type       = "<disk-type>"                   # From matrix or default - Options: "Premium_LRS", "Standard_LRS", "StandardSSD_LRS", null to use defaults
  
  # AKS CLI system node pool configuration (from matrix or pipeline parameters)
  aks_cli_system_node_pool = {
    name        = "<system-pool-name>"                      # System node pool name - e.g., "system", "agentpool"
    node_count  = <node-count>                              # Number of nodes - Integer (e.g., 1, 3, 5) - can be overridden by matrix
    vm_size     = "<vm-size>"                              # VM size - e.g., "Standard_D2s_v3", "Standard_D4s_v3", "Standard_D8s_v3" - can be overridden by matrix
    vm_set_type = "<vm-set-type>"                          # VM set type - Options: "VirtualMachineScaleSets", "AvailabilitySet"
  }
  
  # AKS CLI user node pools configuration (from matrix or pipeline parameters)
  aks_cli_user_node_pool = [
    {
      name        = "<user-pool-name>"                      # User node pool name - e.g., "user01", "workernodes"
      node_count  = <node-count>                            # Number of nodes - Integer (e.g., 1, 2, 5, 10) - can be overridden by matrix
      vm_size     = "<vm-size>"                            # VM size - e.g., "Standard_D2s_v3", "Standard_D4s_v3", "Standard_D8s_v3" - can be overridden by matrix
      vm_set_type = "<vm-set-type>"                        # VM set type - Options: "VirtualMachineScaleSets", "AvailabilitySet"
      optional_parameters = [                               # Optional CLI parameters for node pool creation
        {
          name  = "<parameter-name>"                        # Parameter name - e.g., "enable-cluster-autoscaler", "min-count", "max-count", "node-taints"
          value = "<parameter-value>"                       # Parameter value - e.g., "true", "1", "10", "key=value:NoSchedule" - can be overridden by matrix
        }
      ]
    }
  ]
}

# Owner of the scenario - Default: "azure_devops"
# NOTE: This can be set in the pipeline variables section
owner = "<owner>"                                           # Owner identifier - e.g., "azure_devops", "aks", "team-name"

# Scenario name - Must be within 30 characters
# NOTE: This should match the pipeline variable SCENARIO_NAME
scenario_name = "<scenario-name>"                           # Scenario identifier - e.g., "basic-aks-test", "perf-eval-test", "network-test"

# Scenario type
# NOTE: This should match the pipeline variable SCENARIO_TYPE  
scenario_type = "<scenario-type>"                           # Type of scenario - e.g., "perf-eval", "functionality", "reliability", "security"

# Deletion delay - Time duration after which resources can be deleted
deletion_delay = "<deletion-delay>"                         # Time format: "1h", "2h", "4h", "24h". Default: "2h"

# ==============================================================================
# KEY VAULT CONFIGURATION (Optional)
# ==============================================================================

# Key Vault configuration for AKS KMS encryption (ETCD encryption at rest)
# Remove this section if KMS encryption is not needed
key_vault_config_list = [
  {
    name = "<key-vault-name>"                              # Key Vault name (3-20 chars) - e.g., "akskms", "mykeyvault"
                                                           # NOTE: A 4-character random suffix will be added automatically for global uniqueness
    keys = [                                               # List of encryption keys to create
      {
        key_name = "<key-name>"                            # Encryption key name - e.g., "kms-encryption-key", "etcd-key"
      }
    ]
  }
]

# ==============================================================================
# PUBLIC IP CONFIGURATION (Optional)
# ==============================================================================

# List of public IP configurations - Remove this section if no public IPs needed
public_ip_config_list = [
  {
    name              = "<public-ip-name>"                  # Public IP name - e.g., "test-public-ip-01", "lb-public-ip"
    count             = <ip-count>                          # Number of IPs to create - Integer (default: 1)
    allocation_method = "<allocation-method>"               # Allocation method - Options: "Static", "Dynamic" (default: "Static")
    sku               = "<sku>"                            # SKU tier - Options: "Basic", "Standard" (default: "Standard")
    zones             = [<availability-zones>]              # Availability zones - e.g., ["1"], ["1", "2", "3"], [] for no zones (default: [])
  }
]

# ==============================================================================
# NETWORK CONFIGURATION (Optional)
# ==============================================================================

# Network configuration for VNets, subnets, NSGs - Remove this section if using default networking
network_config_list = [
  {
    role               = "<network-role>"                   # Network role - e.g., "server", "client", "pod2pod"
    vnet_name          = "<vnet-name>"                     # Virtual network name - e.g., "test-vnet", "aks-vnet"
    vnet_address_space = "<vnet-cidr>"                     # VNet address space - e.g., "10.0.0.0/16", "192.168.0.0/16"
    
    # Subnets configuration
    subnet = [
      {
        name                         = "<subnet-name>"      # Subnet name - e.g., "aks-subnet", "default-subnet"
        address_prefix               = "<subnet-cidr>"      # Subnet CIDR - e.g., "10.0.1.0/24", "192.168.1.0/24"
        service_endpoints            = [<service-endpoints>] # Service endpoints - e.g., ["Microsoft.ContainerRegistry", "Microsoft.Storage"], [] for none
        pls_network_policies_enabled = <pls-enabled>       # Private link service policies - true/false (optional)
        delegations = [                                     # Subnet delegations (optional)
          {
            name                       = "<delegation-name>" # Delegation name - e.g., "aks-delegation"
            service_delegation_name    = "<service-name>"   # Service name - e.g., "Microsoft.ContainerService/managedClusters"
            service_delegation_actions = [<actions>]        # Actions - e.g., ["Microsoft.Network/virtualNetworks/subnets/action"]
          }
        ]
      }
    ]
    
    network_security_group_name = "<nsg-name>"             # Network security group name - e.g., "test-nsg", "aks-nsg"
    
    # Network interface and public IP associations (optional)
    nic_public_ip_associations = [
      {
        nic_name              = "<nic-name>"               # Network interface name - e.g., "test-nic-01"
        subnet_name           = "<subnet-name>"            # Subnet name to associate with - must match subnet name above
        ip_configuration_name = "<ip-config-name>"         # IP configuration name - e.g., "internal", "primary"
        public_ip_name        = "<public-ip-name>"         # Public IP name - must match public IP name above
        count                 = <nic-count>                # Number of NICs - Integer (default: 1)
      }
    ]
    
    # Network security rules
    nsr_rules = [
      {
        name                       = "<rule-name>"          # Rule name - e.g., "AllowSSH", "AllowHTTPS"
        priority                   = <priority>             # Priority - Integer (100-4096), lower = higher priority
        direction                  = "<direction>"          # Direction - Options: "Inbound", "Outbound"
        access                     = "<access>"             # Access - Options: "Allow", "Deny"
        protocol                   = "<protocol>"           # Protocol - Options: "Tcp", "Udp", "Icmp", "*"
        source_port_range          = "<src-port>"          # Source port - e.g., "*", "80", "80-90"
        destination_port_range     = "<dest-port>"         # Destination port - e.g., "22", "443", "80-90"
        # NOTE: If using Azure Bastion for SSH, do NOT use "*" here for port 22.
        # Use the AzureBastionSubnet CIDR as the source_address_prefix instead.
        source_address_prefix      = "<src-address>"       # Source address - e.g., "10.0.10.0/27", "10.0.0.0/16", "192.168.1.100"
        destination_address_prefix = "<dest-address>"      # Destination address - e.g., "*", "10.0.0.0/16", "VirtualNetwork"
      }
    ]
    
    # NAT gateway associations (optional)
    nat_gateway_associations = [
      {
        nat_gateway_name = "<nat-gateway-name>"            # NAT gateway name - e.g., "test-nat-gateway"
        public_ip_names  = [<public-ip-list>]             # Public IP names - e.g., ["test-public-ip-01"]
        subnet_names     = [<subnet-list>]                # Subnet names - e.g., ["aks-subnet"]
      }
    ]
    
    # Route tables for User Defined Routing (UDR) (optional)
    # Used for controlling network traffic flow, commonly with Azure Firewall or NVA
    # IMPORTANT: Route tables must be created BEFORE AKS cluster when using outbound_type = "userDefinedRouting"
    route_tables = [
      {
        name                         = "<route-table-name>"          # Route table name - e.g., "aks-udr-rt", "firewall-rt"
        bgp_route_propagation_enabled = <enable-bgp>                # Enable BGP route propagation - true/false (optional, default: true)
        
        # Routes configuration
        routes = [
          {
            name                   = "<route-name>"                   # Route name - e.g., "default-route", "internet-via-firewall"
            address_prefix         = "<destination-cidr>"             # Destination address prefix - e.g., "0.0.0.0/0", "10.0.0.0/16"
            next_hop_type          = "<next-hop-type>"               # Next hop type - Options: "VirtualAppliance", "VnetLocal", "Internet", "None"
            next_hop_in_ip_address = "<next-hop-ip>"                 # Next hop IP address - e.g., "10.0.2.4" (required when next_hop_type is "VirtualAppliance", otherwise optional)
          }
        ]
        
        # Subnet associations - which subnets should use this route table
        subnet_associations = [
          {
            subnet_name = "<subnet-name>"                            # Subnet name - must match subnet name above, e.g., "aks-subnet"
          }
        ]
      }
    ]
  }
]

# ==============================================================================
# DNS ZONES CONFIGURATION (Optional)
# ==============================================================================

# DNS zones to create - Remove this section if no DNS zones needed
dns_zones = [
  {
    name = "<dns-zone-name>"                               # DNS zone name - e.g., "example.com", "test.local"
  }
]

# ==============================================================================
# AKS CLUSTER CONFIGURATION (Optional)
# ==============================================================================

# AKS cluster configurations using Terraform provider - Remove this section if using CLI-based deployment only
aks_config_list = [
  {
    role        = "<cluster-role>"                         # Cluster role - e.g., "server", "client", "cas"
    aks_name    = "<cluster-name>"                         # AKS cluster name - e.g., "test-aks-cluster", "perf-cluster"
    subnet_name = "<subnet-name>"                          # Subnet name for AKS - must match subnet name in network_config_list (optional)
    dns_prefix  = "<dns-prefix>"                          # DNS prefix for cluster - e.g., "testaks", "perfcluster"
    
    # Network profile configuration (optional)
    network_profile = {
      network_plugin      = "<network-plugin>"             # Network plugin - Options: "azure", "kubenet", "none" (optional)
      network_plugin_mode = "<plugin-mode>"               # Plugin mode - Options: "overlay", "bridge" (optional, for azure CNI)
      network_policy      = "<network-policy>"            # Network policy - Options: "azure", "cilium", "calico" (optional)
      network_dataplane   = "<network-dataplane>"         # Network dataplane - Options: "azure", "cilium" (optional)
      outbound_type       = "<outbound-type>"             # Outbound type - Options: "loadBalancer", "userDefinedRouting", "managedNATGateway", "userAssignedNATGateway" (optional)
      pod_cidr            = "<pod-cidr>"                  # Pod CIDR - e.g., "10.244.0.0/16" (optional, for kubenet)
      service_cidr        = "<service-cidr>"              # Service CIDR - e.g., "10.0.3.0/24" (optional)
      dns_service_ip      = "<dns-service-ip>"            # DNS service IP - e.g., "10.0.3.10" (optional, must be within service_cidr)
    }
    
    # Service mesh profile (optional)
    service_mesh_profile = {
      mode      = "<mesh-mode>"                           # Service mesh mode - Options: "Istio", "Disabled"
      revisions = [<mesh-revisions>]                      # Mesh revisions - e.g., ["asm-1-18", "asm-1-19"]
    }
    
    sku_tier = "<sku-tier>"                               # SKU tier - Options: "Free", "Standard", "Premium"
    
    # Default (system) node pool
    default_node_pool = {
      name                         = "<pool-name>"         # Node pool name - e.g., "system", "default"
      subnet_name                  = "<subnet-name>"      # Subnet name (optional)
      node_count                   = <node-count>         # Number of nodes - Integer (e.g., 1, 3, 5)
      vm_size                      = "<vm-size>"          # VM size - e.g., "Standard_D2s_v3", "Standard_D4s_v3"
      os_sku                       = "<os-sku>"           # OS SKU - Options: "Ubuntu", "CBLMariner", "Windows2019", "Windows2022" (optional, default: "Ubuntu")
      os_disk_type                 = "<disk-type>"        # OS disk type - Options: "Managed", "Ephemeral" (optional, default: "Managed")
      os_disk_size_gb              = <disk-size>          # OS disk size in GB - Integer (optional, e.g., 30, 100, 128)
      only_critical_addons_enabled = <critical-only>      # Only critical addons - true/false
      temporary_name_for_rotation  = "<temp-name>"        # Temporary name for rotation - e.g., "systemtemp", "defaulttmp"
      max_pods                     = <max-pods>           # Max pods per node - Integer (optional, e.g., 30, 110, 250)
      node_labels                  = {                    # Node labels (optional)
        "<label-key>" = "<label-value>"                   # e.g., "nodepool-type" = "system", "environment" = "test"
      }
      min_count                    = <min-count>          # Minimum node count for autoscaling (optional)
      max_count                    = <max-count>          # Maximum node count for autoscaling (optional)
      auto_scaling_enabled         = <autoscaling>        # Enable autoscaling - true/false (optional, default: false)
    }
    
    # Additional node pools (optional)
    extra_node_pool = [
      {
        name                 = "<pool-name>"              # Node pool name - e.g., "user01", "workernodes"
        subnet_name          = "<subnet-name>"           # Subnet name (optional)
        node_count           = <node-count>              # Number of nodes - Integer
        vm_size              = "<vm-size>"               # VM size
        os_type              = "<os-type>"               # OS type - Options: "Linux", "Windows" (optional, default: "Linux")
        os_sku               = "<os-sku>"                # OS SKU (optional)
        os_disk_type         = "<disk-type>"             # OS disk type (optional)
        os_disk_size_gb      = <disk-size>               # OS disk size (optional)
        max_pods             = <max-pods>                # Max pods per node (optional)
        ultra_ssd_enabled    = <ultra-ssd>               # Enable Ultra SSD - true/false (optional, default: false)
        zones                = [<zones>]                 # Availability zones - e.g., ["1"], ["1", "2", "3"] (optional)
        node_taints          = [<taints>]                # Node taints - e.g., ["key=value:NoSchedule"] (optional)
        node_labels          = {                         # Node labels (optional)
          "<label-key>" = "<label-value>"
        }
        min_count            = <min-count>               # Minimum count for autoscaling (optional)
        max_count            = <max-count>               # Maximum count for autoscaling (optional)
        auto_scaling_enabled = <autoscaling>             # Enable autoscaling (optional)
      }
    ]
    
    # Role assignments (optional)
    role_assignment_list = [<role-assignments>]          # Role assignments - e.g., ["Network Contributor", "AcrPull"]
    
    # OIDC and Workload Identity (optional)
    oidc_issuer_enabled       = <oidc-enabled>           # Enable OIDC issuer - true/false (optional, default: false)
    workload_identity_enabled = <workload-identity>      # Enable workload identity - true/false (optional, default: false)
    
    kubernetes_version = "<k8s-version>"                 # Kubernetes version - e.g., "1.28", "1.29", "1.30" (optional)
    edge_zone         = "<edge-zone>"                   # Edge zone (optional) - e.g., "microsoftlosangeles1"
    
    # Auto scaler profile (optional)
    auto_scaler_profile = {
      balance_similar_node_groups      = <balance>       # Balance similar node groups - true/false (optional, default: false)
      expander                         = "<expander>"    # Expander type - Options: "random", "most-pods", "least-waste", "priority" (optional, default: "random")
      max_graceful_termination_sec     = "<termination>" # Max graceful termination - e.g., "600", "30" (optional, default: "600")
      max_node_provisioning_time       = "<provision>"   # Max node provisioning time - e.g., "15m", "10m" (optional, default: "15m")
      max_unready_nodes                = <max-unready>   # Max unready nodes - Integer (optional, default: 3)
      max_unready_percentage           = <unready-pct>   # Max unready percentage - Integer (optional, default: 45)
      new_pod_scale_up_delay           = "<scale-delay>" # New pod scale up delay - e.g., "10s", "0s" (optional, default: "10s")
      scale_down_delay_after_add       = "<delay-add>"   # Scale down delay after add - e.g., "10m", "2m" (optional, default: "10m")
      scale_down_delay_after_delete    = "<delay-del>"   # Scale down delay after delete - e.g., "10s", "1m" (optional, default: "10s")
      scale_down_delay_after_failure   = "<delay-fail>"  # Scale down delay after failure - e.g., "3m", "1m" (optional, default: "3m")
      scale_down_unneeded              = "<unneeded>"    # Scale down unneeded - e.g., "10m", "3m" (optional, default: "10m")
      scale_down_unready               = "<unready>"     # Scale down unready - e.g., "20m", "5m" (optional, default: "20m")
      scale_down_utilization_threshold = "<threshold>"   # Scale down utilization threshold - e.g., "0.5", "0.7" (optional, default: "0.5")
      scan_interval                    = "<scan>"        # Scan interval - e.g., "10s", "20s" (optional, default: "10s")
      empty_bulk_delete_max            = "<bulk-delete>" # Empty bulk delete max - e.g., "10", "200" (optional, default: "10")
      skip_nodes_with_local_storage    = <skip-storage>  # Skip nodes with local storage - true/false (optional, default: true)
      skip_nodes_with_system_pods      = <skip-system>   # Skip nodes with system pods - true/false (optional, default: true)
    }
    
    # Web app routing (optional)
    web_app_routing = {
      dns_zone_names = [<dns-zones>]                     # DNS zone names - e.g., ["example.com"] (must match dns_zones above)
    }
    
    # KMS configuration (optional)
    kms_config = {
      key_name       = "<key-name>"                        # Key name - must match key_name in key_vault_config_list
      key_vault_name = "<key-vault-name>"                  # Key vault name - must match name in key_vault_config_list
      network_access = "<network-access>"                  # Network access - Options: "Public", "Private" (optional, default: "Public")
    }
  }
]

# ==============================================================================
# AKS CLI CONFIGURATION (Optional)
# ==============================================================================

# AKS CLI configurations for clusters created via Azure CLI - Remove this section if using Terraform provider only
aks_cli_config_list = [
  {
    role     = "<cluster-role>"                           # Cluster role - e.g., "client", "server", "cas"
    aks_name = "<cluster-name>"                           # AKS cluster name - e.g., "test-aks-cli-cluster", "perf-cli-cluster"
    sku_tier = "<sku-tier>"                              # SKU tier - Options: "Free", "Standard", "Premium"
    
    managed_identity_name         = "<identity-name>"     # Managed identity name (optional) - e.g., "test-managed-identity"
    subnet_name                   = "<subnet-name>"      # Subnet name (optional) - must match subnet name in network_config_list
    kubernetes_version            = "<k8s-version>"      # Kubernetes version (optional) - e.g., "1.28", "1.29", "1.30"
    aks_custom_headers            = [<custom-headers>]    # Custom headers for AKS API calls - List of strings or []
    use_custom_configurations     = <use-custom>         # Use custom configurations - true/false (optional, default: false)
    use_aks_preview_cli_extension = <use-preview>        # Use AKS preview CLI extension - true/false (optional, default: true)
    use_aks_preview_private_build = <use-private>        # Use AKS preview private build - true/false (optional, default: false)
    
    # Default node pool for CLI-created cluster (optional)
    default_node_pool = {
      name        = "<pool-name>"                         # Node pool name - e.g., "system", "agentpool"
      node_count  = <node-count>                          # Number of nodes - Integer (e.g., 1, 3, 5)
      vm_size     = "<vm-size>"                          # VM size - e.g., "Standard_D2s_v3", "Standard_D4s_v3"
      vm_set_type = "<vm-set-type>"                      # VM set type - Options: "VirtualMachineScaleSets", "AvailabilitySet" (optional, default: "VirtualMachineScaleSets")
    }
    
    # Extra node pools for CLI-created cluster (optional)
    extra_node_pool = [
      {
        name        = "<pool-name>"                       # Node pool name - e.g., "user01", "workernodes"
        node_count  = <node-count>                        # Number of nodes - Integer
        vm_size     = "<vm-size>"                        # VM size
        vm_set_type = "<vm-set-type>"                    # VM set type (optional)
        optional_parameters = [                           # Optional CLI parameters for node pool creation
          {
            name  = "<parameter-name>"                    # Parameter name - Options: "enable-cluster-autoscaler", "min-count", "max-count", "node-taints", "node-labels", "zones"
            value = "<parameter-value>"                   # Parameter value - e.g., "true", "1", "10", "key=value:NoSchedule", "key=value", "1,2,3"
          }
        ]
      }
    ]
    
    # Optional parameters for cluster creation
    optional_parameters = [
      {
        name  = "<parameter-name>"                        # Parameter name - Options: "enable-managed-identity", "network-plugin", "network-policy", "enable-addons", "workspace-resource-id"
        value = "<parameter-value>"                       # Parameter value - e.g., "true", "azure", "calico", "monitoring,http_application_routing"
      }
    ]
    
    dry_run = <dry-run>                                   # Dry run mode - true/false (optional, default: false). If true, only prints commands without executing
    
    # KMS configuration (optional)
    kms_config = {
      key_name       = "<key-name>"                        # Key name - must match key_name in key_vault_config_list
      key_vault_name = "<key-vault-name>"                  # Key vault name - must match name in key_vault_config_list
      network_access = "<network-access>"                  # Network access - Options: "Public", "Private" (optional, default: "Public")
    }
  }
]

# ==============================================================================
# USAGE EXAMPLES AND COMMON CONFIGURATIONS
# ==============================================================================

# Example 1: Simple AKS cluster with basic configuration
# scenario_name = "basic-aks"
# scenario_type = "functionality"
# owner = "aks"
# deletion_delay = "2h"

# Example 2: Performance evaluation cluster
# scenario_name = "perf-eval-cluster"
# scenario_type = "perf-eval"
# owner = "aks"
# deletion_delay = "4h"

# Example 3: Multi-node pool cluster for testing
# aks_config_list = [{
#   role = "server"
#   aks_name = "multi-pool-test"
#   dns_prefix = "multipool"
#   sku_tier = "Standard"
#   default_node_pool = {
#     name = "system"
#     node_count = 3
#     vm_size = "Standard_D2s_v3"
#     only_critical_addons_enabled = true
#     temporary_name_for_rotation = "systemtmp"
#   }
#   extra_node_pool = [{
#     name = "workers"
#     node_count = 2
#     vm_size = "Standard_D4s_v3"
#     auto_scaling_enabled = true
#     min_count = 1
#     max_count = 10
#   }]
#   kubernetes_version = "1.29"
# }]

# Example 4: AKS with User Defined Routing (UDR) through Azure Firewall
# scenario_name = "aks-udr-firewall"
# scenario_type = "perf-eval"
# owner = "aks"
# deletion_delay = "4h"
#
# network_config_list = [{
#   role = "udr-network"
#   vnet_name = "aks-udr-vnet"
#   vnet_address_space = "10.0.0.0/16"
#   subnet = [
#     {
#       name = "aks-subnet"
#       address_prefix = "10.0.1.0/24"
#     },
#     {
#       name = "firewall-subnet"
#       address_prefix = "10.0.2.0/24"
#     }
#   ]
#   network_security_group_name = ""
#   nic_public_ip_associations = []
#   nsr_rules = []
#   route_tables = [{
#     name = "aks-firewall-rt"
#     bgp_route_propagation_enabled = false
#     routes = [
#       {
#         name = "internet-via-firewall"
#         address_prefix = "0.0.0.0/0"
#         next_hop_type = "VirtualAppliance"
#         next_hop_in_ip_address = "10.0.2.4"  # Azure Firewall IP
#       },
#       {
#         name = "local-vnet"
#         address_prefix = "10.0.0.0/16"
#         next_hop_type = "VnetLocal"
#       }
#     ]
#     subnet_associations = [
#       { subnet_name = "aks-subnet" }
#     ]
#   }]
# }]
#
# aks_config_list = [{
#   role = "udr-cluster"
#   aks_name = "aks-udr"
#   dns_prefix = "aksudr"
#   subnet_name = "aks-subnet"
#   sku_tier = "Standard"
#   network_profile = {
#     network_plugin = "azure"
#     network_plugin_mode = "overlay"
#     outbound_type = "userDefinedRouting"  # Required for UDR
#     pod_cidr = "10.244.0.0/16"
#     service_cidr = "10.245.0.0/16"
#     dns_service_ip = "10.245.0.10"
#   }
#   default_node_pool = {
#     name = "system"
#     node_count = 3
#     vm_size = "Standard_D4s_v3"
#     os_disk_type = "Managed"
#     only_critical_addons_enabled = false
#     temporary_name_for_rotation = "systemtmp"
#   }
#   extra_node_pool = []
# }]

# Example 5: Hub-and-Spoke topology with multiple route tables
# network_config_list = [{
#   role = "spoke-network"
#   vnet_name = "spoke-vnet"
#   vnet_address_space = "10.1.0.0/16"
#   subnet = [
#     {
#       name = "aks-subnet"
#       address_prefix = "10.1.1.0/24"
#     },
#     {
#       name = "services-subnet"
#       address_prefix = "10.1.2.0/24"
#     }
#   ]
#   network_security_group_name = ""
#   nic_public_ip_associations = []
#   nsr_rules = []
#   route_tables = [
#     {
#       name = "aks-to-hub-rt"
#       routes = [
#         {
#           name = "to-hub"
#           address_prefix = "10.0.0.0/16"  # Hub VNet CIDR
#           next_hop_type = "VirtualAppliance"
#           next_hop_in_ip_address = "10.0.0.4"  # NVA in hub
#         },
#         {
#           name = "to-internet"
#           address_prefix = "0.0.0.0/0"
#           next_hop_type = "VirtualAppliance"
#           next_hop_in_ip_address = "10.0.0.4"
#         }
#       ]
#       subnet_associations = [{ subnet_name = "aks-subnet" }]
#     },
#     {
#       name = "services-rt"
#       routes = [
#         {
#           name = "direct-internet"
#           address_prefix = "0.0.0.0/0"
#           next_hop_type = "Internet"
#         }
#       ]
#       subnet_associations = [{ subnet_name = "services-subnet" }]
#     }
#   ]
# }]

# ==============================================================================
# VALIDATION NOTES
# ==============================================================================

# - scenario_name must be within 30 characters
# - If aks_network_policy is "azure" or "cilium", aks_network_dataplane must match or be null
# - deletion_delay format: "1h", "2h", "4h", "24h" etc.
# - Windows agent pool names cannot be longer than 6 characters
# - dns_service_ip must be within service_cidr range
# - Kubernetes versions: Check AKS supported versions (typically 1.28, 1.29, 1.30, 1.31)
# - VM sizes: Standard_D2s_v3, Standard_D4s_v3, Standard_D8s_v3, Standard_B2s, etc.
# - Network plugins: "azure" (recommended), "kubenet", "none"
# - Network policies: "azure", "cilium", "calico" (null to disable)
# - OS SKUs: "Ubuntu" (default), "CBLMariner", "Windows2019", "Windows2022"
# - Availability zones: ["1"], ["2"], ["3"], ["1", "2"], ["1", "2", "3"], [] (no zones)
# - Route table next_hop_type options: "VirtualAppliance", "VnetLocal", "Internet", "None"
# - When using outbound_type = "userDefinedRouting", route table must be created before AKS cluster
# - next_hop_in_ip_address is required when next_hop_type is "VirtualAppliance"
# - Route tables can be associated with multiple subnets
# - For UDR with AKS, ensure routes allow connectivity to required Azure services (ACR, AAD, AKS control plane, etc.)

# ==============================================================================
# PIPELINE MATRIX ADVANCED USAGE
# ==============================================================================

# Matrix parameters enable running multiple test variations with the same base infrastructure.
# The pipeline matrix can override any json_input parameter to create different test scenarios.

# Example: Testing different VM sizes and Kubernetes versions
# matrix:
#   small_cluster:
#     k8s_machine_type: "Standard_D2s_v3"
#     aks_kubernetes_version: "1.28"
#     aks_sku_tier: "Free"
#   medium_cluster:
#     k8s_machine_type: "Standard_D4s_v3"
#     aks_kubernetes_version: "1.29"
#     aks_sku_tier: "Standard"
#   large_cluster:
#     k8s_machine_type: "Standard_D8s_v3"
#     aks_kubernetes_version: "1.30"
#     aks_sku_tier: "Premium"

# Example: Testing different network configurations
# matrix:
#   azure_cni:
#     aks_network_policy: "azure"
#     aks_network_dataplane: "azure"
#   cilium_cni:
#     aks_network_policy: "cilium"
#     aks_network_dataplane: "cilium"
#   kubenet:
#     aks_network_policy: null
#     aks_network_dataplane: null

# Example: Testing different node pool configurations
# matrix:
#   single_pool:
#     aks_cli_system_node_pool:
#       node_count: 3
#       vm_size: "Standard_D2s_v3"
#   multi_pool:
#     aks_cli_system_node_pool:
#       node_count: 3
#       vm_size: "Standard_D2s_v3"
#     aks_cli_user_node_pool:
#       - name: "workers"
#         node_count: 5
#         vm_size: "Standard_D4s_v3"

# How Matrix Works with Infrastructure:
# 1. The same tfvars file is used for all matrix jobs
# 2. Matrix parameters override specific json_input values
# 3. Each matrix job creates separate Azure resources with different configurations
# 4. All jobs run in parallel (subject to max_parallel setting)
# 5. Results can be compared across different configurations

# Common Matrix Use Cases:
# - VM size comparisons (Standard_D2s_v3 vs Standard_D4s_v3 vs Standard_D8s_v3)
# - Kubernetes version compatibility testing (1.28 vs 1.29 vs 1.30)
# - Network plugin performance testing (Azure CNI vs Cilium vs Kubenet)
# - SKU tier feature testing (Free vs Standard vs Premium)
# - Storage performance testing (Premium_LRS vs Standard_LRS vs StandardSSD_LRS)
# - Multi-region deployment testing
# - Node pool scaling scenarios
# - OS SKU comparisons (Ubuntu vs CBLMariner vs Windows)

# Matrix Parameter Sources:
# - Pipeline stage parameters: Automatically provided (run_id, region)
# - Pipeline variables: Set in pipeline definition (SCENARIO_NAME, SCENARIO_TYPE)
# - Matrix overrides: Custom per-job values defined in pipeline matrix section
# - Default values: Fallback values when not specified in matrix

# Advanced Matrix Scenarios:
# - Cross-cloud comparisons: Same test logic across Azure, AWS, GCP
# - Performance benchmarking: Different configurations for load testing
# - Feature validation: Testing new AKS features across multiple configurations
# - Regression testing: Ensuring compatibility across versions and configurations