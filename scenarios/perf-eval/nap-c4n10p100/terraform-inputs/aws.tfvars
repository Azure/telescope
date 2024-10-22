scenario_type  = "perf-eval"
scenario_name  = "nap-c4n10p100"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role           = "nap"
    vpc_name       = "nap-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "nap-subnet"
        cidr_block              = "10.0.32.0/19"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "nap-subnet-2"
        cidr_block              = "10.0.64.0/19"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "nap-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "nap-subnet-rt-assoc"
        subnet_name      = "nap-subnet"
        route_table_name = "internet-rt"
      },
      {
        name             = "nap-subnet-rt-assoc-2"
        subnet_name      = "nap-subnet-2"
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
  role             = "nap"
  eks_name         = "nap-c4n10p100"
  enable_cluster_autoscaler = true
  vpc_name         = "nap-vpc"
	kubernetes_version = "1.30"
  policy_arns      = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "nap-c4n10p100-ng"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.large"]
      min_size       = 1
      max_size       = 10
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      taints = [ ]
    }
  ]
  eks_addons = []
}]
