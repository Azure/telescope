scenario_type  = "perf-eval"
scenario_name  = "slo"
deletion_delay = "120h"
owner          = "aks"

network_config_list = [
  {
    role           = "slo"
    vpc_name       = "slo-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "slo-subnet"
        cidr_block              = "10.0.0.0/24"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "slo-subnet-2"
        cidr_block              = "10.0.1.0/24"
        zone_suffix             = "b"
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
        name             = "slo-subnet-rt-assoc"
        subnet_name      = "slo-subnet"
        route_table_name = "internet-rt"
      },
      {
        name             = "slo-subnet-rt-assoc-2"
        subnet_name      = "slo-subnet-2"
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
  role        = "slo"
  eks_name    = "slo"
  vpc_name    = "slo-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSServicePolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
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
      name           = "userpool1"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5.4xlarge"]
      min_size       = 100
      max_size       = 100
      desired_size   = 100
      capacity_type  = "ON_DEMAND"
      taints = [
        {
          key    = "slo"
          value  = "true"
          effect = "NoSchedule"
        }
      ]
    }
  ]

  eks_addons = [
    { name = "coredns"},
    { name = "vpc-cni" },
    { name = "kube-proxy" }
  ]
}]
