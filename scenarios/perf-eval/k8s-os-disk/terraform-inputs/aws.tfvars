scenario_type  = "perf-eval"
scenario_name  = "k8s-os-disk"
deletion_delay = "2h"
owner          = "storage"
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
  eks_name    = "disk-eks"
  vpc_name    = "client-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "default"
      ami_type       = "AL2_x86_64"
      instance_types = ["m5.4xlarge"]
      min_size       = 2
      max_size       = 2
      desired_size   = 2
      capacity_type  = "ON_DEMAND"
    },
    {
      name           = "user"
      ami_type       = "AL2_x86_64"
      instance_types = ["m7i.4xlarge"]
      min_size       = 1
      max_size       = 1
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      labels         = { fio-dedicated = "true" }
      taints = [
        {
          key    = "fio-dedicated"
          value  = "true"
          effect = "NO_EXECUTE"
        },
        {
          key    = "fio-dedicated"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
      block_device_mappings = [
        {
          device_name = "/dev/xvda"
          ebs = {
            delete_on_termination = true
            iops                  = 5000
            throughput            = 200
            volume_size           = 1024
            volume_type           = "gp3"
          }
        }
      ]
    }
  ]
  kubernetes_version = "1.31"
}]
