variables {
  scenario_type  = "perf-eval"
  scenario_name  = "my_scenario"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    "run_id" : "123456789",
    "region" : "us-east-1",
    "creation_time" : "2024-11-12T16:39:54Z"
  }

  network_config_list = [
    {
      role           = "my-role"
      vpc_name       = "my-vpc"
      vpc_cidr_block = "10.0.0.0/16"
      subnet = [
        {
          name                    = "my-subnet"
          cidr_block              = "10.0.32.0/19"
          zone_suffix             = "a"
          map_public_ip_on_launch = true
        }
      ]
      security_group_name = "my-sg"
      route_tables = [
        {
          name       = "internet-rt"
          cidr_block = "0.0.0.0/0"
        }
      ],
      route_table_associations = [
        {
          name             = "my-subnet-rt-assoc"
          subnet_name      = "my-subnet"
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
    role                    = "my-role"
    eks_name                = "auto_mode_true"
    vpc_name                = "my-vpc"
    auto_mode               = true
    policy_arns             = ["AmazonEKS_CNI_Policy"]
    eks_managed_node_groups = []
    eks_addons              = []
    }, {
    role                    = "my-role"
    eks_name                = "auto_mode_false"
    vpc_name                = "my-vpc"
    auto_mode               = false
    policy_arns             = ["AmazonEKS_CNI_Policy"]
    eks_managed_node_groups = []
    eks_addons              = []
  }]
}

run "eks_auto_mode_enabled" {

  command = plan

  # Define the assertions to validate the resources
  assert {
    condition     = module.eks["auto_mode_true"].eks_cluster.bootstrap_self_managed_addons == false
    error_message = "EKS Auto Mode should disable self-managed addons"
  }

  assert {
    condition     = module.eks["auto_mode_true"].eks_cluster.compute_config[0].enabled == true
    error_message = "EKS Auto Mode should enable compute_config"
  }

  assert {
    condition     = module.eks["auto_mode_true"].eks_cluster.storage_config[0].block_storage[0].enabled == true
    error_message = "EKS Auto Mode should enable block storage"
  }

  assert {
    condition     = module.eks["auto_mode_true"].eks_cluster.kubernetes_network_config[0].elastic_load_balancing[0].enabled == true
    error_message = "EKS Auto Mode should enable elastic load balancing"
  }

  assert {
    condition     = alltrue([for item in ["AmazonEKSBlockStoragePolicy", "AmazonEKSComputePolicy", "AmazonEKSLoadBalancingPolicy", "AmazonEKSNetworkingPolicy"] : contains(keys(module.eks["auto_mode_true"].eks_role_policy_attachments), item)])
    error_message = "EKS Auto Mode should attach AmazonEKSBlockStoragePolicy, AmazonEKSComputePolicy, AmazonEKSLoadBalancingPolicy, and AmazonEKSNetworkingPolicy"
  }

  expect_failures = [check.deletion_due_time]
}

run "eks_auto_mode_disabled" {
  command = plan

  # Define the assertions to validate the resources
  assert {
    condition     = module.eks["auto_mode_false"].eks_cluster.bootstrap_self_managed_addons == true
    error_message = "EKS Auto Mode should enable self-managed addons when disabled"
  }

  assert {
    condition     = length(module.eks["auto_mode_false"].eks_cluster.compute_config) == 0
    error_message = "EKS Auto Mode should not enable compute_config when disabled"
  }

  assert {
    condition     = length(module.eks["auto_mode_false"].eks_cluster.storage_config) == 0
    error_message = "EKS Auto Mode should not enable block storage when disabled"
  }


  # note: kubernetes_network_config.elastic_load_balancing.enabled is unknown during planing

  expect_failures = [check.deletion_due_time]
}
