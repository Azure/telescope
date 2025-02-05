scenario_type  = "perf-eval"
scenario_name  = "cas-c4n10p100"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role           = "cas"
    vpc_name       = "cas-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "cas-subnet"
        cidr_block              = "10.0.32.0/19"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "cas-subnet-2"
        cidr_block              = "10.0.64.0/19"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      },
      {
        name                    = "cas-subnet-3"
        cidr_block              = "10.0.96.0/19"
        zone_suffix             = "c"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "cas-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "cas-subnet-rt-assoc"
        subnet_name      = "cas-subnet"
        route_table_name = "internet-rt"
      },
      {
        name             = "cas-subnet-rt-assoc-2"
        subnet_name      = "cas-subnet-2"
        route_table_name = "internet-rt"
      },
      {
        name             = "cas-subnet-rt-assoc-3"
        subnet_name      = "cas-subnet-3"
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
  role                      = "cas"
  eks_name                  = "cas-c4n10p100"
  enable_cluster_autoscaler = true
  vpc_name                  = "cas-vpc"
  policy_arns               = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly", "AmazonSSMManagedInstanceCore"]
  eks_managed_node_groups = [
    {
      name           = "default"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.large"]
      min_size       = 5
      max_size       = 5
      desired_size   = 5
      capacity_type  = "ON_DEMAND"
    },
    {
      name           = "userpool"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5.xlarge"]
      min_size       = 1
      max_size       = 11
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      labels         = { "cas" = "dedicated" }
      taints         = []
    }
  ]
  eks_addons         = []
  kubernetes_version = "1.31"
  auto_scaler_profile = {
    scale_down_delay_after_add     = "2m"
    scale_down_delay_after_failure = "1m"
    scale_down_unneeded            = "3m"
    scale_down_unready             = "5m"
    scan_interval                  = "20s"
    max_unready_percentage         = 90
    skip_nodes_with_local_storage  = false
    empty_bulk_delete_max          = "11"
    max_graceful_termination_sec   = "30"
  }
}]
