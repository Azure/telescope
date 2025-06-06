scenario_type  = "perf-eval"
scenario_name  = "slo-servicediscovery"
deletion_delay = "8h"
owner          = "aks"

network_config_list = [
  {
    role                       = "slo"
    vpc_name                   = "slo-vpc"
    vpc_cidr_block             = "10.0.0.0/16"
    secondary_ipv4_cidr_blocks = ["10.1.0.0/16"]
    subnet = [
      {
        name                    = "slo-subnet-1"
        cidr_block              = "10.0.0.0/16"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "slo-subnet-2"
        cidr_block              = "10.1.0.0/17"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      },
      {
        name                    = "slo-subnet-3"
        cidr_block              = "10.1.128.0/17"
        zone_suffix             = "c"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "slo-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "slo-subnet-rt-assoc-1"
        subnet_name      = "slo-subnet-1"
        route_table_name = "internet-rt"
      },
      {
        name             = "slo-subnet-rt-assoc-2"
        subnet_name      = "slo-subnet-2"
        route_table_name = "internet-rt"
      },
      {
        name             = "slo-subnet-rt-assoc-3"
        subnet_name      = "slo-subnet-3"
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
  role             = "slo"
  eks_name         = "slo"
  enable_karpenter = false
  vpc_name         = "slo-vpc"
  policy_arns      = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "default"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.4xlarge"]
      min_size       = 5
      max_size       = 5
      desired_size   = 5
      capacity_type  = "ON_DEMAND"
    },
    {
      name           = "prompool"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.16xlarge"]
      min_size       = 1
      max_size       = 1
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      labels         = { "prometheus" = "true" }
    },
    {
      name           = "userpool0"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5a.xlarge"]
      min_size       = 200
      max_size       = 200
      desired_size   = 200
      capacity_type  = "ON_DEMAND"
      labels = {
        "slo"       = "true",
        "agentpool" = "userpool0"
      }
      taints = [
        {
          key    = "slo"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
    },
    {
      name           = "userpool1"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5a.xlarge"]
      min_size       = 200
      max_size       = 200
      desired_size   = 200
      capacity_type  = "ON_DEMAND"
      labels = {
        "slo"       = "true",
        "agentpool" = "userpool1"
      }
      taints = [
        {
          key    = "slo"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
    },
    {
      name           = "userpool2"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5a.xlarge"]
      min_size       = 200
      max_size       = 200
      desired_size   = 200
      capacity_type  = "ON_DEMAND"
      labels = {
        "slo"       = "true",
        "agentpool" = "userpool2"
      }
      taints = [
        {
          key    = "slo"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
    },
    {
      name           = "userpool3"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5a.xlarge"]
      min_size       = 200
      max_size       = 200
      desired_size   = 200
      capacity_type  = "ON_DEMAND"
      labels = {
        "slo"       = "true",
        "agentpool" = "userpool3"
      }
      taints = [
        {
          key    = "slo"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
    },
    {
      name           = "userpool4"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5a.xlarge"]
      min_size       = 200
      max_size       = 200
      desired_size   = 200
      capacity_type  = "ON_DEMAND"
      labels = {
        "slo"       = "true",
        "agentpool" = "userpool4"
      }
      taints = [
        {
          key    = "slo"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
    }
  ]

  eks_addons = [
    {
      name                       = "vpc-cni",
      vpc_cni_warm_prefix_target = 4 # 64 IPs to accomodate 58 Pods (max for m5a.xlarge) + 2 for extras
    },
    { name = "kube-proxy" },
    { name = "coredns" }
  ]
  kubernetes_version = "1.32"
}]
