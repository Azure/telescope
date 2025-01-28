scenario_type  = "perf-eval"
scenario_name  = "apiserver-vn100pod3k"
deletion_delay = "20h"
owner          = "aks"

network_config_list = [
  {
    role           = "client"
    vpc_name       = "client-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "client-subnet"
        cidr_block              = "10.0.0.0/24"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "client-subnet-2"
        cidr_block              = "10.0.1.0/24"
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
  eks_name    = "vn100-p3k"
  vpc_name    = "client-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "idle"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.large"]
      min_size       = 1
      max_size       = 1
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      labels         = { terraform = "true", k8s = "true", role = "apiserver-eval" } # Optional input
    },
    {
      name           = "virtualnodes"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.2xlarge"]
      min_size       = 5
      max_size       = 5
      desired_size   = 5
      capacity_type  = "ON_DEMAND"
      labels         = { terraform = "true", k8s = "true", role = "apiserver-eval" } # Optional input
    },
    {
      name           = "runner"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.4xlarge"]
      min_size       = 3
      max_size       = 3
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
      labels         = { terraform = "true", k8s = "true", role = "apiserver-eval" } # Optional input
    }
  ]

  eks_addons = [
    {
      name = "coredns"
    }
  ]

  kubernetes_version = "1.31"
}]

