scenario_type  = "perf-eval"
scenario_name  = "auto-cluster-pod-startup"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role           = "automatic"
    vpc_name       = "auto-cluster-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "auto-cluster-subnet"
        cidr_block              = "10.0.32.0/19"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "auto-cluster-subnet-2"
        cidr_block              = "10.0.64.0/19"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "auto-cluster-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "auto-cluster-subnet-rt-assoc"
        subnet_name      = "auto-cluster-subnet"
        route_table_name = "internet-rt"
      },
      {
        name             = "auto-cluster-subnet-rt-assoc-2"
        subnet_name      = "auto-cluster-subnet-2"
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
  role     = "automatic"
  eks_name = "auto-cluster-pod-startup"
  vpc_name = "auto-cluster-vpc"
  policy_arns = [
    "AmazonEKSClusterPolicy",
    "AmazonEKSVPCResourceController",
    "AmazonEKS_CNI_Policy",
    "AmazonSSMManagedInstanceCore"
  ]
  auto_mode                 = true
  node_pool_general_purpose = true
  node_pool_system          = true
  eks_managed_node_groups = [
    {
      name           = "prompool"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5.4xlarge"]
      min_size       = 1
      max_size       = 1
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      labels         = { "prometheus" = "true" }
    }
  ]
  eks_addons         = []
  kubernetes_version = "1.32"
}]