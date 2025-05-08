scenario_type  = "perf-eval"
scenario_name  = "pod-diff-node-vnet"
deletion_delay = "2h"
owner          = "aks"
network_config_list = [
  {
    role           = "pod2pod"
    vpc_name       = "pod2pod-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "pod2pod-subnet"
        cidr_block              = "10.0.32.0/19"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "pod2pod-subnet-2"
        cidr_block              = "10.0.64.0/19"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "pod2pod-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "pod2pod-subnet-rt-assoc"
        subnet_name      = "pod2pod-subnet"
        route_table_name = "internet-rt"
      },
      {
        name             = "pod2pod-subnet-rt-assoc-2"
        subnet_name      = "pod2pod-subnet-2"
        route_table_name = "internet-rt"
      }
    ]
    sg_rules = {
      ingress = [
        {
          from_port  = 5201
          to_port    = 5201
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 20005
          to_port    = 20005
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 20000
          to_port    = 20000
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 20003
          to_port    = 20003
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 80
          to_port    = 80
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        }
      ]
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
  role        = "pod2pod"
  eks_name    = "pod-diff-node"
  vpc_name    = "pod2pod-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly", "AmazonSSMManagedInstanceCore"]
  eks_managed_node_groups = [
    {
      name           = "default"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.4xlarge"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      taints         = []
    },
    {
      name           = "client"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.4xlarge"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      labels         = { "app" = "client", "test" = "true" }
      subnet_names   = ["pod2pod-subnet"]
      taints = [
        {
          key    = "dedicated-test"
          value  = "true"
          effect = "NO_SCHEDULE"
        },
        {
          key    = "dedicated-test"
          value  = "true"
          effect = "NO_EXECUTE"
        }
      ]
    },
    {
      name           = "server"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.4xlarge"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      labels         = { "app" = "server", "test" = "true" }
      subnet_names   = ["pod2pod-subnet"]
      taints = [
        {
          key    = "dedicated-test"
          value  = "true"
          effect = "NO_SCHEDULE"
        },
        {
          key    = "dedicated-test"
          value  = "true"
          effect = "NO_EXECUTE"
        }
      ]
    }
  ]
  eks_addons         = [{ name = "vpc-cni" }]
  kubernetes_version = "1.30"
}]
