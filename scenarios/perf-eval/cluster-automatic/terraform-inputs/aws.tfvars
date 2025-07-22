scenario_type  = "perf-eval"
scenario_name  = "cluster-automatic"
deletion_delay = "2h"
owner          = "aks"

network_config_list = [
  {
    role           = "automatic"
    vpc_name       = "automatic-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "automatic-subnet"
        cidr_block              = "10.0.32.0/19"
        zone_suffix             = "a"
        map_public_ip_on_launch = false
      },
      {
        name                    = "automatic-subnet-2"
        cidr_block              = "10.0.64.0/19"
        zone_suffix             = "b"
        map_public_ip_on_launch = false
      },
      {
        name                    = "automatic-public-subnet"
        cidr_block              = "10.0.0.0/24"
        zone_suffix             = "c"
        map_public_ip_on_launch = true
      }
    ]
    security_group_name = "automatic-sg"
    route_tables = [
      {
        name             = "internet-rt"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = null
      },
      {
        name             = "private-rt"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = "nat-gateway"
      }
    ],
    route_table_associations = [
      {
        name             = "automatic-public-subnet-rt-assoc"
        subnet_name      = "automatic-public-subnet"
        route_table_name = "internet-rt"
      },
      {
        name             = "automatic-subnet-rt-assoc"
        subnet_name      = "automatic-subnet"
        route_table_name = "private-rt"
      },
      {
        name             = "automatic-subnet-rt-assoc-2"
        subnet_name      = "automatic-subnet-2"
        route_table_name = "private-rt"
      }
    ]
    sg_rules = {
      ingress = [
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
    },
    nat_gateway_public_ips = [{
      name = "nat-gateway-pip"
    }],
    nat_gateways = [{
      name           = "nat-gateway"
      public_ip_name = "nat-gateway-pip"
      subnet_name    = "automatic-public-subnet"
    }]
  }
]

eks_config_list = [{
  role     = "automatic"
  eks_name = "automatic"
  vpc_name = "automatic-vpc"
  policy_arns = [
    "AmazonEKSClusterPolicy",
    "AmazonEKSVPCResourceController",
    "AmazonEKS_CNI_Policy",
    "AmazonSSMManagedInstanceCore"
  ]
  auto_mode                 = true
  node_pool_general_purpose = true
  node_pool_system          = true
  eks_managed_node_groups   = []
  eks_addons                = []
  kubernetes_version        = "1.32"
}]
