scenario_type  = "perf-eval"
scenario_name  = "k8s-gpu-cluster-crud"
deletion_delay = "2h"
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
  }
]

eks_config_list = [{
  role        = "gpu"
  eks_name    = "gpu-cluster"
  vpc_name    = "gpu-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly", "AmazonSSMManagedInstanceCore"]
  eks_managed_node_groups = [
    {
      name           = "default-ng"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 2
      max_size       = 2
      desired_size   = 2
      capacity_type  = "ON_DEMAND"
      taints = [
        {
          key    = "CriticalAddonsOnly"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
    }
  ]
  eks_addons         = []
  kubernetes_version = "1.33"
}]