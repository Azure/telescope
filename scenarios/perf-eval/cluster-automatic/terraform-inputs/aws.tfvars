# =============================================================================
# ARCHITECTURE OVERVIEW - EKS Automatic Mode Performance Evaluation
# =============================================================================
#
# VPC: automatic-vpc (10.0.0.0/16)
# ├── Public Subnets (Internet-facing)
# │   ├── automatic-public-subnet (10.0.0.0/24, AZ-a)
# │   │   ├── NAT Gateway (nat-gateway) with Elastic IP (nat-gateway-pip)
# │   │   └── Routes to Internet Gateway for direct internet access
# │   └── automatic-public-subnet-2 (10.0.1.0/24, AZ-b)
# │       ├── NAT Gateway (nat-gateway-2) with Elastic IP (nat-gateway-pip-2)
# │       └── Routes to Internet Gateway for direct internet access
# │
# └── Private Subnets (EKS worker nodes)
#     ├── automatic-subnet (10.0.32.0/19, AZ-a)
#     │   └── Routes to nat-gateway for outbound internet traffic
#     └── automatic-subnet-2 (10.0.64.0/19, AZ-b)
#         └── Routes to nat-gateway for outbound internet traffic
#
# Security:
# ├── Security Group: automatic-sg
# │   ├── Ingress: HTTP (port 80) from anywhere
# │   └── Egress: All traffic to anywhere
#
# EKS Configuration:
# ├── Cluster: automatic (Kubernetes 1.32)
# ├── Mode: Auto Mode enabled
# ├── Node Pools: General Purpose + System pools
# └── IAM Policies: EKS, VPC, CNI, SSM access
#
# =============================================================================

# Performance evaluation scenario for EKS automatic mode testing
scenario_type  = "perf-eval"
scenario_name  = "cluster-automatic"
deletion_delay = "2h"  # Auto-cleanup after 2 hours
owner          = "aks"

# Network configuration for EKS cluster with private/public subnet architecture
network_config_list = [
  {
    role           = "automatic"
    vpc_name       = "automatic-vpc"
    vpc_cidr_block = "10.0.0.0/16"  # Provides ~65k IP addresses
    
    # Subnet configuration: 2 private + 2 public subnets for HA across AZs
    subnet = [
      # Private subnets for EKS worker nodes (no direct internet access)
      {
        name                    = "automatic-subnet"
        cidr_block              = "10.0.32.0/19"  # ~8k IPs in AZ-a
        zone_suffix             = "a"
        map_public_ip_on_launch = false
      },
      {
        name                    = "automatic-subnet-2"
        cidr_block              = "10.0.64.0/19"  # ~8k IPs in AZ-b
        zone_suffix             = "b"
        map_public_ip_on_launch = false
      },
      # Public subnets for NAT gateways and load balancers
      {
        name                    = "automatic-public-subnet"
        cidr_block              = "10.0.0.0/24"   # ~250 IPs in AZ-a
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "automatic-public-subnet-2"
        cidr_block              = "10.0.1.0/24"   # ~250 IPs in AZ-b
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      }
    ]
    
    security_group_name = "automatic-sg"
    
    # Routing configuration
    route_tables = [
      # Public route table - direct internet access via IGW
      {
        name             = "internet-rt"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = null  # Uses Internet Gateway instead
      },
      # Private route table - internet access via NAT Gateway
      {
        name             = "private-rt"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = "nat-gateway"  # Routes through NAT for outbound traffic
      },
      {
        name             = "private-rt"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = "nat-gateway-2"  # Routes through NAT for outbound traffic
      }
    ],
    
    # Subnet-to-route-table associations
    route_table_associations = [
      # Public subnets use internet route table
      {
        name             = "automatic-public-subnet-rt-assoc"
        subnet_name      = "automatic-public-subnet"
        route_table_name = "internet-rt"
      },
      {
        name             = "automatic-public-subnet-rt-assoc-2"
        subnet_name      = "automatic-public-subnet-2"
        route_table_name = "internet-rt"
      },
      # Private subnets use private route table (via NAT)
      {
        name             = "automatic-subnet-rt-assoc"
        subnet_name      = "automatic-subnet"
        route_table_name = "private-rt"
      },
      {
        name             = "automatic-subnet-rt-assoc-2"
        subnet_name      = "automatic-subnet-2"
        route_table_name = "private-rt"
      }
    ]
    
    # Security group rules for cluster access
    # Security group rules for cluster access
    sg_rules = {
      ingress = [
        # Allow HTTP traffic for demo applications
        {
          from_port  = 80
          to_port    = 80
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        }
      ]
      egress = [
        # Allow all outbound traffic
        {
          from_port  = 0
          to_port    = 0
          protocol   = "-1"
          cidr_block = "0.0.0.0/0"
        }
      ]
    },
    
    # Elastic IPs for NAT Gateways (one per AZ for HA)
    nat_gateway_public_ips = [{
      name = "nat-gateway-pip"      # EIP for AZ-a NAT Gateway
    },{
      name = "nat-gateway-pip-2"    # EIP for AZ-b NAT Gateway
    }],
    
    # NAT Gateways for private subnet internet access (one per AZ)
    nat_gateways = [{
      name           = "nat-gateway"              # Primary NAT in AZ-a
      public_ip_name = "nat-gateway-pip"
      subnet_name    = "automatic-public-subnet"
    },{
      name           = "nat-gateway-2"            # Secondary NAT in AZ-b
      public_ip_name = "nat-gateway-pip-2"
      subnet_name    = "automatic-public-subnet-2"
    }]
  }
]

# EKS cluster configuration for automatic mode performance testing
eks_config_list = [{
  role     = "automatic"
  eks_name = "automatic"
  vpc_name = "automatic-vpc"
  
  # IAM policies required for EKS Auto Mode functionality
  policy_arns = [
    "AmazonEKSClusterPolicy",        # Core EKS cluster permissions
    "AmazonEKSVPCResourceController", # VPC resource management
    "AmazonEKS_CNI_Policy",          # Container networking interface
    "AmazonSSMManagedInstanceCore"   # Systems Manager for node management
  ]
  
  # EKS Auto Mode configuration
  auto_mode                 = true   # Enable automatic infrastructure management
  node_pool_general_purpose = true   # Auto-managed general purpose nodes
  node_pool_system          = true   # Auto-managed system/control plane nodes
  
  # Manual node groups and addons disabled for pure auto mode testing
  eks_managed_node_groups   = []     # Let auto mode handle node provisioning
  eks_addons                = []     # Let auto mode handle addon management
  
  kubernetes_version        = "1.32" # Latest Kubernetes version for testing
}]
