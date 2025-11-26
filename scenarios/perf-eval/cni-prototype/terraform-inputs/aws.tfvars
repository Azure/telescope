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
        name                    = "cni-private-subnet-1"
        cidr_block              = "10.0.0.0/20"
        zone_suffix             = "a"
        map_public_ip_on_launch = false
      },
      {
        name                    = "cni-private-subnet-2"
        cidr_block              = "10.0.16.0/20"
        zone_suffix             = "b"
        map_public_ip_on_launch = false
      },
      {
        name                    = "cni-public-subnet-1"
        cidr_block              = "10.0.32.0/20"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "cni-public-subnet-2"
        cidr_block              = "10.0.48.0/20"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "cni-sg"
    route_tables = [
      {
        name             = "internet-rt"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = null
      },
      {
        name             = "private-rt-1"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = "nat-gateway-1"
      },
      {
        name             = "private-rt-2"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = "nat-gateway-2"
      }
    ],
    route_table_associations = [
      {
        name             = "cni-public-rt-assoc-1"
        subnet_name      = "cni-public-subnet-1"
        route_table_name = "internet-rt"
      },
      {
        name             = "cni-public-rt-assoc-2"
        subnet_name      = "cni-public-subnet-2"
        route_table_name = "internet-rt"
      },
      {
        name             = "cni-private-rt-assoc-1"
        subnet_name      = "cni-private-subnet-1"
        route_table_name = "private-rt-1"
      },
      {
        name             = "cni-private-rt-assoc-2"
        subnet_name      = "cni-private-subnet-2"
        route_table_name = "private-rt-2"
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
    nat_gateway_public_ips = [
      {
        name = "nat-gateway-pip-1"
      },
      {
        name = "nat-gateway-pip-2"
      }
    ]
    nat_gateways = [
      {
        name           = "nat-gateway-1"
        public_ip_name = "nat-gateway-pip-1"
        subnet_name    = "cni-public-subnet-1"
      },
      {
        name           = "nat-gateway-2"
        public_ip_name = "nat-gateway-pip-2"
        subnet_name    = "cni-public-subnet-2"
      }
    ]
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
      subnet_names   = ["cni-private-subnet-1", "cni-private-subnet-2"]
      instance_types = ["m6i.4xlarge"]
      min_size       = 3
      max_size       = 3
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
      network_interfaces = {
        associate_public_ip_address = false
        delete_on_termination       = true
      }
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
