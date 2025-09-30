# AWS Terraform Variables Template
# This template helps with onboarding new test scenarios for AWS infrastructure
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
# 2. Terraform Input Variables Step (steps/terraform/set-input-variables-aws.yml):
#    - Collects pipeline stage parameters (run_id, region, creation_time, etc.)
#    - Merges pipeline matrix parameters to override specific values
#    - Constructs the json_input object
#    - Passes it to terraform as TF_VAR_json_input
#
# 3. This tfvars file:
#    - Uses json_input values to configure AWS resources
#    - Allows matrix-based variations for multiple test jobs
#    - Enables running same infrastructure with different configurations
#
# Pipeline Matrix Examples:
# matrix:
#   small_cluster:
#     k8s_machine_type: "m5.large"
#     ena_express: true
#   large_cluster:
#     k8s_machine_type: "m5.4xlarge"
#     ena_express: true
#     capacity_reservation_id: "cr-1234567890abcdef0"
#
# This creates multiple jobs with the same tfvars but different json_input values.

# ==============================================================================
# BASIC CONFIGURATION
# ==============================================================================

# JSON input configuration - main input object containing scenario details
# NOTE: These values are automatically populated by the pipeline - do not set manually
json_input = {
  # Pipeline-provided values (from pipeline stage parameters):
  run_id        = "<run-id>"                               # Auto-generated from pipeline run (e.g., "test-run-001", "perf-001")
  region        = "<aws-region>"                           # From pipeline regions parameter - Available: us-east-1, us-east-2, us-west-1, us-west-2, eu-west-1, eu-west-2, eu-central-1, ap-southeast-1, ap-southeast-2, ap-northeast-1, ap-northeast-2, ap-south-1, ca-central-1, sa-east-1
  creation_time = "<creation-time>"                        # Auto-generated timestamp in RFC3339 format (e.g., "2024-10-17T18:30:42Z") - Must not be more than 1 hour from now
  
  # Matrix-overridable values (can be customized per test job via pipeline matrix):
  user_data_path          = "<user-data-path>"            # From matrix or default - Path to user data script (optional) - e.g., "", "/path/to/userdata.sh"
  k8s_machine_type        = "<instance-type>"             # From matrix or default - Override instance type for EKS nodes - e.g., "m5.large", "m5.xlarge", "c5.2xlarge", null to use defaults
  ena_express             = <ena-express>                  # From matrix or default - Enable ENA Express for enhanced networking - true/false (optional)
  capacity_reservation_id = "<capacity-reservation-id>"   # From matrix or default - Capacity reservation ID (optional) - e.g., "cr-1234567890abcdef0", null if not using
}

# Owner of the scenario
# NOTE: This can be set in the pipeline variables section
owner = "<owner>"                                          # Owner identifier - e.g., "aws_devops", "aks", "team-name"

# Scenario name - Must be within 30 characters
# NOTE: This should match the pipeline variable SCENARIO_NAME
scenario_name = "<scenario-name>"                          # Scenario identifier - e.g., "basic-eks-test", "perf-eval-test", "network-test"

# Scenario type
# NOTE: This should match the pipeline variable SCENARIO_TYPE
scenario_type = "<scenario-type>"                          # Type of scenario - e.g., "perf-eval", "functionality", "reliability", "security"

# Deletion delay - Time duration after which resources can be deleted (max 72h)
deletion_delay = "<deletion-delay>"                        # Time format: "1h", "2h", "4h", "24h", "72h". Must not exceed 72 hours

# ==============================================================================
# NETWORK CONFIGURATION (Optional)
# ==============================================================================

# Network configuration for VPCs, subnets, security groups - Remove this section if using default networking
network_config_list = [
  {
    role                       = "<network-role>"            # Network role - e.g., "server", "client", "pod2pod"
    vpc_name                   = "<vpc-name>"                # VPC name - e.g., "test-vpc", "eks-vpc"
    vpc_cidr_block             = "<vpc-cidr>"                # VPC CIDR block - e.g., "10.0.0.0/16", "192.168.0.0/16"
    secondary_ipv4_cidr_blocks = [<secondary-cidrs>]         # Additional CIDR blocks (optional) - e.g., ["10.1.0.0/16"], [] for none
    
    # Subnets configuration
    subnet = [
      {
        name                    = "<subnet-name>"            # Subnet name - e.g., "eks-subnet-1a", "public-subnet-1a"
        cidr_block              = "<subnet-cidr>"            # Subnet CIDR - e.g., "10.0.1.0/24", "192.168.1.0/24"
        zone_suffix             = "<zone-suffix>"            # Availability zone suffix - Options: "a", "b", "c", "d", "e", "f"
        map_public_ip_on_launch = <map-public-ip>            # Map public IP on launch - true/false
      }
    ]
    
    security_group_name = "<security-group-name>"           # Security group name - e.g., "test-security-group", "eks-sg"
    
    # Route tables configuration
    route_tables = [
      {
        name             = "<route-table-name>"              # Route table name - e.g., "private-route-table", "public-route-table"
        cidr_block       = "<destination-cidr>"              # Destination CIDR - e.g., "0.0.0.0/0" for default route
        nat_gateway_name = "<nat-gateway-name>"              # NAT gateway name (optional) - null for IGW route, NAT gateway name for private subnets
      }
    ]
    
    # Route table associations
    route_table_associations = [
      {
        name             = "<association-name>"              # Association name - e.g., "private-subnet-1a-association"
        subnet_name      = "<subnet-name>"                   # Subnet name - must match subnet name above
        route_table_name = "<route-table-name>"              # Route table name - must match route table name above
      }
    ]
    
    # NAT gateway public IPs (optional)
    nat_gateway_public_ips = [
      {
        name = "<eip-name>"                                  # Elastic IP name - e.g., "test-nat-gateway-eip"
      }
    ]
    
    # NAT gateways (optional)
    nat_gateways = [
      {
        name           = "<nat-gateway-name>"                # NAT gateway name - e.g., "test-nat-gateway"
        public_ip_name = "<eip-name>"                        # Elastic IP name - must match EIP name above
        subnet_name    = "<subnet-name>"                     # Subnet name - must be a public subnet
      }
    ]
    
    # Security group rules
    sg_rules = {
      ingress = [
        {
          from_port  = <from-port>                          # From port - Integer (e.g., 22, 443, 80, 0 for all)
          to_port    = <to-port>                            # To port - Integer (e.g., 22, 443, 80, 0 for all)
          protocol   = "<protocol>"                         # Protocol - Options: "tcp", "udp", "icmp", "-1" (all)
          cidr_block = "<cidr-block>"                       # CIDR block - e.g., "0.0.0.0/0", "10.0.0.0/16", "192.168.1.100/32"
        }
      ],
      egress = [
        {
          from_port  = <from-port>                          # From port
          to_port    = <to-port>                            # To port
          protocol   = "<protocol>"                         # Protocol
          cidr_block = "<cidr-block>"                       # CIDR block
        }
      ]
    }
  }
]

# ==============================================================================
# EKS CLUSTER CONFIGURATION (Optional)
# ==============================================================================

# EKS cluster configurations - Remove this section if not using EKS
eks_config_list = [
  {
    role                      = "<cluster-role>"             # Cluster role - e.g., "server", "client", "pod2pod"
    eks_name                  = "<cluster-name>"             # EKS cluster name - e.g., "test-eks-cluster", "perf-cluster"
    vpc_name                  = "<vpc-name>"                 # VPC name - must match VPC name in network_config_list
    policy_arns               = [<policy-arns>]              # IAM policy ARNs - e.g., ["AmazonEKSClusterPolicy"], ["arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"]
    enable_karpenter          = <enable-karpenter>           # Enable Karpenter for node autoscaling - true/false (optional, default: false)
    enable_cluster_autoscaler = <enable-cas>                 # Enable cluster autoscaler - true/false (optional, default: false, alternative to Karpenter)
    auto_mode                 = <auto-mode>                  # Enable EKS Auto Mode - true/false (optional, default: false)
    node_pool_general_purpose = <general-purpose>            # Create general purpose node pool - true/false (optional, default: false)
    node_pool_system          = <system-pool>                # Create system node pool - true/false (optional, default: false)
    
    # EKS managed node groups
    eks_managed_node_groups = [
      {
        name           = "<node-group-name>"                 # Node group name - e.g., "system-nodes", "worker-nodes"
        ami_type       = "<ami-type>"                        # AMI type - Options: "AL2_x86_64", "AL2_x86_64_GPU", "AL2_ARM_64", "CUSTOM", "WINDOWS_CORE_2019_x86_64", "WINDOWS_FULL_2019_x86_64", "WINDOWS_CORE_2022_x86_64", "WINDOWS_FULL_2022_x86_64"
        instance_types = [<instance-types>]                 # Instance types - e.g., ["m5.large"], ["m5.large", "m5.xlarge"], ["c5.2xlarge"]
        min_size       = <min-size>                          # Minimum size - Integer (e.g., 0, 1, 2)
        max_size       = <max-size>                          # Maximum size - Integer (e.g., 3, 5, 10, 100)
        desired_size   = <desired-size>                      # Desired size - Integer (e.g., 1, 2, 3)
        capacity_type  = "<capacity-type>"                   # Capacity type - Options: "ON_DEMAND", "SPOT" (optional, default: "ON_DEMAND")
        labels = {                                           # Node labels (optional)
          "<label-key>" = "<label-value>"                    # e.g., "nodegroup-type" = "system", "environment" = "test"
        }
        subnet_names   = [<subnet-names>]                    # Subnet names (optional) - e.g., ["eks-subnet-1a", "eks-subnet-1b"], null for all subnets
        ena_express    = <ena-express>                       # Enable ENA Express - true/false (optional)
        taints = [                                           # Node taints (optional)
          {
            key    = "<taint-key>"                           # Taint key - e.g., "CriticalAddonsOnly", "dedicated-test"
            value  = "<taint-value>"                         # Taint value - e.g., "true", "system"
            effect = "<taint-effect>"                        # Taint effect - Options: "NO_SCHEDULE", "NO_EXECUTE", "PREFER_NO_SCHEDULE"
          }
        ]
        
        # Block device mappings for custom storage (optional)
        block_device_mappings = [
          {
            device_name = "<device-name>"                    # Device name - e.g., "/dev/xvda", "/dev/sdf"
            ebs = {
              delete_on_termination = <delete-on-term>       # Delete on termination - true/false (optional, default: true)
              iops                  = <iops>                 # IOPS - Integer (optional, for gp3/io1/io2 volumes)
              throughput            = <throughput>           # Throughput in MiB/s - Integer (optional, for gp3 volumes)
              volume_size           = <volume-size>          # Volume size in GB - Integer (optional, e.g., 20, 100, 500)
              volume_type           = "<volume-type>"        # Volume type - Options: "gp2", "gp3", "io1", "io2", "sc1", "st1" (optional)
            }
          }
        ]
        
        # Capacity reservation specification (optional)
        capacity_reservation_specification = {
          capacity_reservation_preference = "<preference>"   # Preference - Options: "open", "none" (optional)
          capacity_reservation_target = {
            capacity_reservation_id                 = "<reservation-id>"         # Reservation ID (optional) - e.g., "cr-1234567890abcdef0"
            capacity_reservation_resource_group_arn = "<resource-group-arn>"     # Resource group ARN (optional)
          }
        }
        
        # Spot instance configuration (optional)
        instance_market_options = {
          market_type = "<market-type>"                      # Market type - Options: "spot" (optional)
          spot_options = {
            block_duration_minutes         = <duration>     # Block duration in minutes - Integer (optional, 60-360)
            instance_interruption_behavior = "<behavior>"   # Interruption behavior - Options: "hibernate", "stop", "terminate" (optional)
            max_price                      = "<max-price>"  # Maximum price - String (optional, e.g., "0.05")
            spot_instance_type             = "<spot-type>"  # Spot instance type - Options: "one-time", "persistent" (optional)
            valid_until                    = "<valid-until>" # Valid until timestamp - String (optional, RFC3339 format)
          }
        }
        
        # Network interfaces configuration (optional)
        network_interfaces = {
          associate_public_ip_address = <associate-ip>      # Associate public IP - true/false (optional)
          delete_on_termination       = <delete-on-term>    # Delete on termination - true/false (optional)
          interface_type              = "<interface-type>"  # Interface type - Options: "efa", "eni" (optional, "efa" for enhanced networking)
        }
      }
    ]
    
    # EKS addons
    eks_addons = [
      {
        name            = "<addon-name>"                     # Addon name - Options: "vpc-cni", "coredns", "kube-proxy", "aws-ebs-csi-driver", "aws-efs-csi-driver", "adot", "aws-for-fluent-bit"
        version         = "<addon-version>"                  # Addon version (optional) - e.g., "v1.15.1-eksbuild.1", latest if not specified
        service_account = "<service-account>"               # Service account name (optional) - e.g., "aws-node", "ebs-csi-controller-sa"
        policy_arns     = [<addon-policy-arns>]             # Policy ARNs for addon (optional) - e.g., ["arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"]
        configuration_values = {                            # Configuration values (optional)
          env = {
            "<env-var-name>" = "<env-var-value>"             # Environment variables - e.g., "ENABLE_PREFIX_DELEGATION" = "true"
          }
        }
        vpc_cni_warm_prefix_target = <warm-prefixes>        # VPC CNI warm prefix target - Integer (optional, default: 1, for vpc-cni addon only)
        before_compute             = <before-compute>       # Install before compute - true/false (optional, default: false)
      }
    ]
    
    kubernetes_version = "<k8s-version>"                    # Kubernetes version (optional) - e.g., "1.28", "1.29", "1.30", "1.31"
    
    # Auto scaler profile configuration (optional)
    auto_scaler_profile = {
      balance_similar_node_groups      = <balance>          # Balance similar node groups - true/false (optional, default: false)
      expander                         = "<expander>"       # Expander type - Options: "random", "most-pods", "least-waste", "priority" (optional, default: "random")
      max_graceful_termination_sec     = "<termination>"    # Max graceful termination - e.g., "600", "30" (optional, default: "600")
      max_node_provision_time          = "<provision-time>" # Max node provision time - e.g., "15m", "10m" (optional, default: "15m")
      max_unready_nodes                = <max-unready>      # Max unready nodes - Integer (optional, default: 3)
      max_unready_percentage           = <unready-pct>      # Max unready percentage - Integer (optional, default: 45)
      new_pod_scale_up_delay           = "<scale-delay>"    # New pod scale up delay - e.g., "10s", "0s" (optional, default: "10s")
      scale_down_delay_after_add       = "<delay-add>"      # Scale down delay after add - e.g., "10m", "2m" (optional, default: "10m")
      scale_down_delay_after_delete    = "<delay-delete>"   # Scale down delay after delete - e.g., "10s", "1m" (optional, default: "10s")
      scale_down_delay_after_failure   = "<delay-failure>"  # Scale down delay after failure - e.g., "3m", "1m" (optional, default: "3m")
      scale_down_unneeded              = "<unneeded>"       # Scale down unneeded - e.g., "10m", "3m" (optional, default: "10m")
      scale_down_unready               = "<unready>"        # Scale down unready - e.g., "20m", "5m" (optional, default: "20m")
      scale_down_utilization_threshold = "<threshold>"      # Scale down utilization threshold - e.g., "0.5", "0.7" (optional, default: "0.5")
      scan_interval                    = "<scan>"           # Scan interval - e.g., "10s", "20s" (optional, default: "10s")
      empty_bulk_delete_max            = "<bulk-delete>"    # Empty bulk delete max - e.g., "10", "200" (optional, default: "10")
      skip_nodes_with_local_storage    = <skip-storage>     # Skip nodes with local storage - true/false (optional, default: true)
      skip_nodes_with_system_pods      = <skip-system>      # Skip nodes with system pods - true/false (optional, default: true)
    }
    
    enable_cni_metrics_helper = <cni-metrics>              # Enable CNI metrics helper - true/false (optional, default: false)
  }
]

# ==============================================================================
# USAGE EXAMPLES AND COMMON CONFIGURATIONS
# ==============================================================================

# Example 1: Simple EKS cluster with basic configuration
# scenario_name = "basic-eks"
# scenario_type = "functionality"
# owner = "aks"
# deletion_delay = "2h"
# json_input = {
#   run_id = "basic-001"
#   region = "us-east-2"
#   creation_time = "2024-10-17T18:30:42Z"
# }

# Example 2: Performance evaluation cluster
# scenario_name = "perf-eval-cluster"
# scenario_type = "perf-eval"
# owner = "aks"
# deletion_delay = "4h"

# Example 3: Multi-node group EKS cluster
# eks_config_list = [{
#   role = "server"
#   eks_name = "multi-node-test"
#   vpc_name = "test-vpc"
#   policy_arns = ["AmazonEKSClusterPolicy"]
#   eks_managed_node_groups = [{
#     name = "system"
#     ami_type = "AL2_x86_64"
#     instance_types = ["m5.large"]
#     min_size = 1
#     max_size = 5
#     desired_size = 3
#     capacity_type = "ON_DEMAND"
#   }, {
#     name = "workers"
#     ami_type = "AL2_x86_64"
#     instance_types = ["m5.xlarge"]
#     min_size = 2
#     max_size = 10
#     desired_size = 4
#     capacity_type = "SPOT"
#   }]
#   eks_addons = [
#     { name = "vpc-cni" },
#     { name = "coredns" },
#     { name = "kube-proxy" }
#   ]
#   kubernetes_version = "1.29"
# }]

# ==============================================================================
# VALIDATION NOTES
# ==============================================================================

# - scenario_name must be within 30 characters
# - creation_time must be RFC3339 format and not more than 1 hour from now
# - deletion_delay must not exceed 72 hours
# - Kubernetes versions: Check EKS supported versions (typically 1.28, 1.29, 1.30, 1.31)
# - Instance types: m5.large, m5.xlarge, c5.2xlarge, t3.medium, etc.
# - AMI types: AL2_x86_64 (most common), AL2_ARM_64, AL2_x86_64_GPU for GPU workloads
# - Capacity types: "ON_DEMAND" (reliable), "SPOT" (cost-effective but interruptible)
# - EBS volume types: "gp3" (recommended), "gp2", "io1", "io2" for high IOPS
# - Taint effects: "NO_SCHEDULE", "NO_EXECUTE", "PREFER_NO_SCHEDULE"
# - Common addons: vpc-cni (networking), coredns (DNS), kube-proxy (networking), aws-ebs-csi-driver (storage)
# - AWS regions: us-east-1, us-east-2, us-west-1, us-west-2, eu-west-1, eu-central-1, ap-southeast-1, etc.
# - Zone suffixes: "a", "b", "c" (minimum 2 zones recommended for HA)

# ==============================================================================
# PIPELINE MATRIX ADVANCED USAGE
# ==============================================================================

# Matrix parameters enable running multiple test variations with the same base infrastructure.
# The pipeline matrix can override any json_input parameter to create different test scenarios.

# Example: Testing different instance types and configurations
# matrix:
#   performance_small:
#     k8s_machine_type: "m5.large"
#     ena_express: false
#   performance_medium:
#     k8s_machine_type: "m5.xlarge" 
#     ena_express: true
#   performance_large:
#     k8s_machine_type: "m5.4xlarge"
#     ena_express: true
#     capacity_reservation_id: "cr-1234567890abcdef0"

# Example: Testing different networking configurations
# matrix:
#   standard_networking:
#     ena_express: false
#   enhanced_networking:
#     ena_express: true
#   reserved_capacity:
#     ena_express: true
#     capacity_reservation_id: "cr-1234567890abcdef0"

# How Matrix Works with Infrastructure:
# 1. The same tfvars file is used for all matrix jobs
# 2. Matrix parameters override specific json_input values
# 3. Each matrix job creates separate AWS resources with different configurations
# 4. All jobs run in parallel (subject to max_parallel setting)
# 5. Results can be compared across different configurations

# Common Matrix Use Cases:
# - Instance type comparisons (m5.large vs m5.xlarge vs c5.2xlarge)
# - Network performance testing (ENA Express on/off)
# - Storage performance testing (gp2 vs gp3 vs io1)
# - Kubernetes version compatibility testing
# - Capacity reservation vs on-demand pricing
# - Multi-region deployment testing

# Matrix Parameter Sources:
# - Pipeline stage parameters: Automatically provided (run_id, region, creation_time)
# - Pipeline variables: Set in pipeline definition (SCENARIO_NAME, SCENARIO_TYPE)
# - Matrix overrides: Custom per-job values defined in pipeline matrix section
# - Default values: Fallback values when not specified in matrix