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
        cidr_block              = "10.0.0.0/24"
        zone_suffix             = "a"
        map_public_ip_on_launch = true
        tags                    = { "karpenter.sh/discovery" = "nap-c4n10p100" }
      },
			{
        name                    = "nap-subnet-2"
        cidr_block              = "10.0.1.0/24"
        zone_suffix             = "b"
        map_public_ip_on_launch = true
        tags                    = { "karpenter.sh/discovery" = "nap-c4n10p100" }
      },
			{
        name                    = "nap-subnet-3"
        cidr_block              = "10.0.2.0/24"
        zone_suffix             = "c"
        map_public_ip_on_launch = true
        tags                    = { "karpenter.sh/discovery" = "nap-c4n10p100" }
      }
    ]
    security_group_name = "nap-sg"
    security_group_tags = { "karpenter.sh/discovery" = "nap-c4n10p100" }
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
			},
			      {
				name             = "nap-subnet-rt-assoc-3"
				subnet_name      = "nap-subnet-3"
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
  role        = "nap"
  eks_name    = "nap-c4n10p100"
	override_cluster_name = true
	install_karpenter = true
	cloudformation_template_file_name = "cloudformation"
  vpc_name    = "nap-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly","AmazonSSMManagedInstanceCore"]
  eks_managed_node_groups = [
    {
      name           = "nap-c4n10p100-ng"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.large"]
      min_size       = 1
      max_size       = 2
      desired_size   = 2
      capacity_type  = "ON_DEMAND"
      taints = [
        {
          key    = "CriticalAddonsOnly"
          value  = "true"
          effect = "NO_SCHEDULE"
        }
      ]
      labels = { terraform = "true", k8s = "true" }
    }
  ]
  pod_associations = {
    namespace            = "kube-system"
    service_account_name = "karpenter"
    role_arn_name        = "nap-c4n10p100-PodIdentityRole"
  }
  eks_addons = [
    {
      name = "eks-pod-identity-agent"
    }
  ]
}]