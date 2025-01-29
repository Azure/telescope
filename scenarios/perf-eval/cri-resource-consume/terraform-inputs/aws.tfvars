scenario_type  = "perf-eval"
scenario_name  = "cri-resource-consume"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role           = "client"
    vpc_name       = "client-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "client-subnet"
        cidr_block              = "10.0.0.0/17"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "client-subnet-2"
        cidr_block              = "10.0.128.0/17"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "client-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "client-subnet-rt-assoc"
        subnet_name      = "client-subnet"
        route_table_name = "internet-rt"
      },
      {
        name             = "client-subnet-rt-assoc-2"
        subnet_name      = "client-subnet-2"
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
  role        = "client"
  eks_name    = "cri-resource-consume"
  vpc_name    = "client-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "default"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5.4xlarge"]
      min_size       = 3
      max_size       = 3
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
    },
    {
      name           = "prompool"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5.4xlarge"]
      min_size       = 1
      max_size       = 1
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      labels         = { "prometheus" = "true" }
    },
    {
      name           = "userpool0"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5.4xlarge"]
      min_size       = 10
      max_size       = 10
      desired_size   = 10
      capacity_type  = "ON_DEMAND"
      taints = [
        {
          key    = "cri-resource-consume"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
      labels = {
        "cri-resource-consume" = "true",
        "agentpool"            = "userpool0"
      }
    }
  ]

  eks_addons = [
    {
      name = "coredns"
    },
    {
      name = "vpc-cni"
    },
    {
      name = "kube-proxy"
    }
  ]
  kubernetes_version = "1.31"
}]
