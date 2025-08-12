scenario_type  = "perf-eval"
scenario_name  = "k8s-gpu-cluster-crud"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role           = "gpu"
    vpc_name       = "gpu-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "gpu-private-subnet-1"
        cidr_block              = "10.0.32.0/19"
        zone_suffix             = "a"
        map_public_ip_on_launch = false
      },
      {
        name                    = "gpu-private-subnet-2"
        cidr_block              = "10.0.64.0/19"
        zone_suffix             = "c"
        map_public_ip_on_launch = false
      },
      {
        name                    = "gpu-private-subnet-3"
        cidr_block              = "10.0.96.0/19"
        zone_suffix             = "f"
        map_public_ip_on_launch = false
      },
      {
        name                    = "gpu-public-subnet-1"
        cidr_block              = "10.0.0.0/24"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "gpu-public-subnet-2"
        cidr_block              = "10.0.1.0/24"
        zone_suffix             = "f"
        map_public_ip_on_launch = true
      },
      {
        name                    = "gpu-public-subnet-3"
        cidr_block              = "10.0.2.0/24"
        zone_suffix             = "c"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "gpu-sg"
    route_tables = [
      {
        name             = "internet-rt"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = null
      },
      {
        name             = "private-rt"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = "nat-gateway" # Routes through NAT for outbound traffic
      }
    ],
    route_table_associations = [
      {
        name             = "gpu-public-rt-assoc"
        subnet_name      = "gpu-public-subnet-1"
        route_table_name = "internet-rt"
      },
      {
        name             = "gpu-public-rt-assoc-2"
        subnet_name      = "gpu-public-subnet-2"
        route_table_name = "internet-rt"
      },
      {
        name             = "gpu-public-rt-assoc-3"
        subnet_name      = "gpu-public-subnet-3"
        route_table_name = "internet-rt"
      },
      {
        name             = "gpu-private-rt-assoc-1"
        subnet_name      = "gpu-private-subnet-1"
        route_table_name = "private-rt"
      },
      {
        name             = "gpu-private-rt-assoc-2"
        subnet_name      = "gpu-private-subnet-2"
        route_table_name = "private-rt"
      },
      {
        name             = "gpu-private-rt-assoc-3"
        subnet_name      = "gpu-private-subnet-3"
        route_table_name = "private-rt"
      }
    ]
    sg_rules = {
      ingress = []
      egress = [
        {
          from_port  = 0
          to_port    = 0
          protocol   = "-1"
          cidr_block = "0.0.0.0/0"
        }
      ]
    }
    nat_gateway_public_ips = [
      {
        name = "nat-gateway-pip"
      }
    ]
    nat_gateways = [
      {
        name           = "nat-gateway"
        public_ip_name = "nat-gateway-pip"
        subnet_name    = "gpu-public-subnet-1"
      }
    ]
  }
]

eks_config_list = [{
  role     = "gpu"
  eks_name = "gpu-cluster"
  vpc_name = "gpu-vpc"
  policy_arns = [
    "AmazonEKSClusterPolicy",
    "AmazonEKSVPCResourceController",
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryReadOnly",
    "AmazonSSMManagedInstanceCore"
  ]
  eks_managed_node_groups = [
    {
      name           = "default"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.4xlarge"]
      subnet_names   = ["gpu-public-subnet-1", "gpu-public-subnet-2", "gpu-public-subnet-3"]
      min_size       = 2
      max_size       = 2
      desired_size   = 2
      capacity_type  = "ON_DEMAND"
      network_interfaces = {
        associate_public_ip_address = true
        delete_on_termination       = true
      }
    }
  ]
  eks_addons = [
    {
      name = "vpc-cni"
    }
  ]
  kubernetes_version = "1.33"
}]
