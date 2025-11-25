scenario_type  = "perf-eval"
scenario_name  = "cni-prototype"
deletion_delay = "72h"
owner          = "aks"

network_config_list = [
  {
    role           = "cni"
    vpc_name       = "cni-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "cni-subnet-1"
        cidr_block              = "10.0.0.0/20"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "cni-subnet-2"
        cidr_block              = "10.0.16.0/20"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      },
      {
        name                    = "cni-subnet-3"
        cidr_block              = "10.0.32.0/20"
        zone_suffix             = "c"
        map_public_ip_on_launch = true
      },
      {
        name                    = "cni-subnet-4"
        cidr_block              = "10.0.48.0/20"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "cni-subnet-5"
        cidr_block              = "10.0.64.0/20"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      },
    ]
    security_group_name = "cni-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "cni-subnet-rt-assoc-1"
        subnet_name      = "cni-subnet-1"
        route_table_name = "internet-rt"
      },
      {
        name             = "cni-subnet-rt-assoc-2"
        subnet_name      = "cni-subnet-2"
        route_table_name = "internet-rt"
      },
      {
        name             = "cni-subnet-rt-assoc-3"
        subnet_name      = "cni-subnet-3"
        route_table_name = "internet-rt"
      },
      {
        name             = "cni-subnet-rt-assoc-4"
        subnet_name      = "cni-subnet-4"
        route_table_name = "internet-rt"
      },
      {
        name             = "cni-subnet-rt-assoc-5"
        subnet_name      = "cni-subnet-5"
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
  role        = "cni"
  eks_name    = "cni-prototype"
  vpc_name    = "cni-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "default"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m6i.4xlarge"]
      min_size       = 3
      max_size       = 3
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
    }
  ]

  eks_addons = [
    {
      name = "coredns"
    },
    {
      name = "kube-proxy"
    }
  ]
  kubernetes_version = "1.33"
}]
