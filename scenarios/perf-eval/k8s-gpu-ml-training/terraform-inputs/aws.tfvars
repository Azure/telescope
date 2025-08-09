scenario_type  = "perf-eval"
scenario_name  = "k8s-gpu-ml-training"
deletion_delay = "72h"
owner          = "aks"

network_config_list = [
  {
    role                       = "gpu"
    vpc_name                   = "gpu-vpc"
    vpc_cidr_block             = "10.0.0.0/16"
    secondary_ipv4_cidr_blocks = ["10.1.0.0/16"]
    subnet = [
      {
        name                    = "gpu-subnet-1"
        cidr_block              = "10.0.0.0/16"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "gpu-subnet-2"
        cidr_block              = "10.1.0.0/17"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      },
      {
        name                    = "gpu-subnet-3"
        cidr_block              = "10.1.128.0/17"
        zone_suffix             = "c"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "gpu-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "gpu-subnet-rt-assoc"
        subnet_name      = "gpu-subnet-1"
        route_table_name = "internet-rt"
      },
      {
        name             = "gpu-subnet-rt-assoc-2"
        subnet_name      = "gpu-subnet-2"
        route_table_name = "internet-rt"
      },
      {
        name             = "gpu-subnet-rt-assoc-3"
        subnet_name      = "gpu-subnet-3"
        route_table_name = "internet-rt"
      }
    ]
    sg_rules = {
      ingress = [
        {
          from_port  = 22
          to_port    = 22
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        }
      ]
      egress = [
        {
          from_port  = 0
          to_port    = 0
          protocol   = "-1"
          cidr_block = "0.0.0.0/0"
        }
      ]
    }
  }
]

eks_config_list = [{
  role        = "gpu"
  eks_name    = "gpu-ml-training"
  vpc_name    = "gpu-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly", "AmazonSSMManagedInstanceCore"]
  eks_managed_node_groups = [
    {
      name           = "default"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.4xlarge"]
      min_size       = 2
      max_size       = 2
      desired_size   = 2
      capacity_type  = "ON_DEMAND"
    },
    {
      name = "user"
      # ami_type       = "AL2023_x86_64_NVIDIA"
      ami_type = "AL2_x86_64_GPU"
      # instance_types = ["g6.48xlarge"]
      instance_types = ["p4d.24xlarge"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      capacity_type  = "CAPACITY_BLOCK"
      capacity_reservation_specification = {
        capacity_reservation_preference = "capacity-reservations-only"
      }
      instance_market_options = {
        market_type = "capacity-block"
      }
      network_interfaces = {
        delete_on_termination = true
        interface_type        = "efa"
      }
    }
  ]
  eks_addons = [
    {
      name = "vpc-cni"
    }
  ]
  kubernetes_version = "1.32"
}]
