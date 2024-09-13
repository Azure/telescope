scenario_type  = "perf-eval"
scenario_name  = "nap-10n100p"
deletion_delay = "20h"
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
        tags                    = { "karpenter.sh/discovery" = "nap-10n100p" }
      }
    ]
    security_group_name = "nap-sg"
		security_group_tags = { "karpenter.sh/discovery" = "nap-10n100p" }
    route_tables = [
      {
        name       = "internet-rt-1"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "nap-subnet-rt-assoc"
        subnet_name      = "nap-subnet"
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
  eks_name    = "nap-10n100p"
  vpc_name    = "nap-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "nap-10n100p-ng"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.large"]
      min_size       = 5
      max_size       = 5
      desired_size   = 5
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
		service_account_name = "karpernter"
		role_arn_name        = "KarpenterControllerPolicy"
	}
  eks_addons = [
    {
      name = "eks-pod-identity-agent"
    }
  ]
}]

