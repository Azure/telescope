scenario_type  = "perf-eval"
scenario_name  = "storage-pod-failover-same-zone"
deletion_delay = "6h"
owner          = "aks"
network_config_list = [
  {
    role           = "client"
    vpc_name       = "client-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [
      {
        name                    = "client-subnet"
        cidr_block              = "10.0.0.0/17"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
      },
      {
        name                    = "client-subnet-2"
        cidr_block              = "10.0.128.0/17"
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
          from_port  = 2222
          to_port    = 2222
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


vm_config_list = []

loadbalancer_config_list = []

eks_config_list = [{
  role        = "client"
  eks_name    = "perfevalpodfailoversz"
  vpc_name    = "client-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "node-group-1"
      ami_type       = "AL2_x86_64"
      instance_types = ["t2.large"]
      subnet_ids     = ["client-subnet"]
      min_size       = 6
      max_size       = 6
      desired_size   = 6
    }
  ]
  eks_addons = [
    {
      name            = "aws-ebs-csi-driver"
      service_account = "ebs-csi-controller-sa"
      policy_arns     = ["service-role/AmazonEBSCSIDriverPolicy"]
    }
  ]
}]
