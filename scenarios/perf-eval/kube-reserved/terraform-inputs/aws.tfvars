scenario_type  = "perf-eval"
scenario_name  = "kube-reserved"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role           = "kube-reserved"
    vpc_name       = "kube-reserved-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "kube-reserved-subnet-1"
        cidr_block              = "10.0.32.0/19"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "kube-reserved-subnet-2"
        cidr_block              = "10.0.64.0/19"
        zone_suffix             = "c"
        map_public_ip_on_launch = true
      },
      {
        name                    = "kube-reserved-subnet-3"
        cidr_block              = "10.0.96.0/19"
        zone_suffix             = "c"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "kube-reserved-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "kube-reserved-subnet-rt-assoc-1"
        subnet_name      = "kube-reserved-subnet-1"
        route_table_name = "internet-rt"
      },
      {
        name             = "kube-reserved-subnet-rt-assoc-2"
        subnet_name      = "kube-reserved-subnet-2"
        route_table_name = "internet-rt"
      },
      {
        name             = "kube-reserved-subnet-rt-assoc-3"
        subnet_name      = "kube-reserved-subnet-3"
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
  role        = "kube-reserved"
  eks_name    = "kube-reserved"
  vpc_name    = "kube-reserved-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "default"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.4xlarge"]
      min_size       = 4
      max_size       = 4
      desired_size   = 4
      capacity_type  = "ON_DEMAND"
    },
    {
      name           = "userpool0"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.4xlarge"]
      min_size       = 3
      max_size       = 3
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
      taints = [
        {
          key    = "kube-reserved"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
      labels = {
        "kube-reserved" = "true",
        "agentpool"     = "userpool0"
      }
    }
  ]

  eks_addons = [
    {
      name        = "vpc-cni",
      version     = "v1.18.3-eksbuild.2",
      policy_arns = ["AmazonEKS_CNI_Policy"]
    },
    { name = "kube-proxy" },
    { name = "coredns" }
  ]

  kubernetes_version = "1.30"
}]
