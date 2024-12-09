basic_cluster_list = [{
  role        = "client"
  eks_name    = "vn10-p100"
  vpc_name    = "client-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "idle"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.large"]
      min_size       = 1
      max_size       = 1
      desired_size   = 1
      capacity_type  = "ON_DEMAND"
      labels         = { terraform = "true", k8s = "true", role = "apiserver-eval" } # Optional input
    },
    {
      name           = "virtualnodes"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.2xlarge"]
      min_size       = 5
      max_size       = 5
      desired_size   = 5
      capacity_type  = "ON_DEMAND"
      labels         = { terraform = "true", k8s = "true", role = "apiserver-eval" } # Optional input
    },
    {
      name           = "runner"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.4xlarge"]
      min_size       = 3
      max_size       = 3
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
      labels         = { terraform = "true", k8s = "true", role = "apiserver-eval" } # Optional input
    }
  ]

  eks_addons = [
    {
      name = "coredns"
    }
  ]
}]

cas_cluster_list = [{
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
      min_size       = 0
      max_size       = 10
      desired_size   = 0
      capacity_type  = "ON_DEMAND"
      labels         = { "cas" = "dedicated" }
      taints         = []
    }
  ]
  eks_addons         = []
  kubernetes_version = "1.31"
  auto_scaler_profile = {
    scale_down_delay_after_add = "0m"
    scale_down_unneeded        = "0m"
  }
}]

nap_cluster_list = [{
  role             = "nap"
  eks_name         = "nap-c4n10p100"
  enable_karpenter = true
  vpc_name         = "nap-vpc"
  policy_arns      = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly", "AmazonSSMManagedInstanceCore"]
  eks_managed_node_groups = [
    {
      name           = "nap-c4n10p100-ng"
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
    }
  ]
  eks_addons = []
}]
