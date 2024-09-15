scenario_type  = "perf-eval"
scenario_name  = "nap-c4n10p100"
deletion_delay = "2h"
owner          = "aks"

karpenter_config = {
  cluster_name        = "nap-c4n10p100-sumanth"
  eks_cluster_version = "1.30"
  vpc_cidr            = "10.0.0.0/16"
  eks_managed_node_group = {
    name           = "nap-c4n10p100-sumanth-ng"
    instance_types = ["m4.large"]
    min_size       = 1
    max_size       = 2
    desired_size   = 2
    capacity_type  = "ON_DEMAND"
  }
  karpenter_chart_version = "1.0.1"
}
