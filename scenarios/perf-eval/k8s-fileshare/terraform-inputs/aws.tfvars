scenario_type   = "perf-eval"
scenario_name   = "k8s-fileshare"
deletion_delay  = "2h"
efs_name_prefix = "k8s-efs"
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
      ingress = [
        {
          from_port  = 2049
          to_port    = 2049
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

vm_config_list           = []
loadbalancer_config_list = []

eks_config_list = [{
  role        = "client"
  eks_name    = "files-eks"
  vpc_name    = "client-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "node-group-1"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5.4xlarge"]
      min_size       = 2
      max_size       = 2
      desired_size   = 2
      labels         = { terraform = "true", k8s = "true", role = "perf-eval", nodepool = "system" }
      taints         = []
    },
    {
      name           = "node-group-2"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5.4xlarge"]
      min_size       = 3
      max_size       = 3
      desired_size   = 3
      labels         = { terraform = "true", k8s = "true", role = "perf-eval", nodepool = "user" }
      taints = [
        {
          key    = "fio-dedicated"
          value  = "true"
          effect = "NO_EXECUTE"
        }
      ]
    }
  ]

  eks_addons = [{
    name            = "aws-efs-csi-driver"
    service_account = "efs-csi-*"
    policy_arns     = ["service-role/AmazonEFSCSIDriverPolicy"]
    }
  ]
}]