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
    role                      = "my-role"
    eks_name                  = "auto_mode_true"
    vpc_name                  = "my-vpc"
    auto_mode                 = true
    node_pool_general_purpose = true
    node_pool_system          = true
    policy_arns               = ["AmazonEKS_CNI_Policy"]
    eks_managed_node_groups   = []
    eks_addons                = []
    }, {
    role                    = "my-role"
    eks_name                = "auto_mode_false"
    vpc_name                = "my-vpc"
    auto_mode               = false
    policy_arns             = ["AmazonEKS_CNI_Policy"]
    eks_managed_node_groups = []
    eks_addons              = []
    }, {
    role                      = "my-role"
    eks_name                  = "auto_mode_with_metrics_addon"
    vpc_name                  = "my-vpc"
    auto_mode                 = true
    node_pool_general_purpose = true
    node_pool_system          = true
    policy_arns               = ["AmazonEKS_CNI_Policy"]
    eks_managed_node_groups   = []
    eks_addons                = [{
      name = "metrics-server"
    }]
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

  # Test that compute_config node_pools is null (as expected for Auto Mode)
  assert {
    condition     = module.eks["auto_mode_true"].eks_cluster.compute_config[0].node_pools == null
    error_message = "EKS Auto Mode compute_config should have null node_pools as custom NodePools are created separately"
  }

  assert {
    condition     = module.eks["auto_mode_true"].eks_cluster.storage_config[0].block_storage[0].enabled == true
    error_message = "EKS Auto Mode should enable block storage"
  }

  assert {
    condition     = module.eks["auto_mode_true"].eks_cluster.kubernetes_network_config[0].elastic_load_balancing[0].enabled == true
    error_message = "EKS Auto Mode should enable elastic load balancing"
  }

  # Test that metrics-server is deployed via terraform_data resource when Auto Mode is enabled and metrics-server addon is not configured
  assert {
    condition     = length(module.eks["auto_mode_true"].apply_metrics_server_addon) == 1
    error_message = "EKS Auto Mode should deploy metrics-server via manifest when addon is not configured"
  }

  # Test that metrics-server addon resource is NOT created when using manifest deployment
  assert {
    condition     = !contains(keys(module.eks["auto_mode_true"].eks_addon.after_compute), "metrics-server")
    error_message = "EKS Auto Mode should not create metrics-server addon when using manifest deployment"
  }

  assert {
    condition     = alltrue([for item in ["AmazonEKSBlockStoragePolicy", "AmazonEKSComputePolicy", "AmazonEKSLoadBalancingPolicy", "AmazonEKSWorkerNodeMinimalPolicy", "AmazonEKSNetworkingPolicy"] : contains(keys(module.eks["auto_mode_true"].eks_role_policy_attachments), item)])
    error_message = "EKS Auto Mode should attach the required Auto Mode policies: AmazonEKSBlockStoragePolicy, AmazonEKSComputePolicy, AmazonEKSLoadBalancingPolicy, AmazonEKSWorkerNodeMinimalPolicy and AmazonEKSNetworkingPolicy"
  }

  assert {
    condition     = can(jsondecode(module.eks["auto_mode_true"].automode_controller_policy[0].policy))
    error_message = "Auto Mode controller policy should be valid JSON"
  }

  # Test that Auto Mode controller policy attachment is created
  assert {
    condition     = length(module.eks["auto_mode_true"].automode_controller_policy_attachments) == 1
    error_message = "Auto Mode controller policy attachment should be created"
  }

  # Test that EKS access entry is created for Auto Mode
  assert {
    condition     = length(module.eks["auto_mode_true"].node_pool_entry) == 1
    error_message = "Auto Mode EKS access entry should be created"
  }

  # Test that EKS access policy association is created for Auto Mode
  assert {
    condition     = length(module.eks["auto_mode_true"].node_pool_policy) == 1
    error_message = "EKS access policy association should be created for Auto Mode"
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

  # Test that metrics-server manifest deployment is not created when Auto Mode is disabled
  assert {
    condition     = length(module.eks["auto_mode_false"].apply_metrics_server_addon) == 0
    error_message = "EKS Auto Mode should not deploy metrics-server via manifest when disabled"
  }

  # Test that metrics-server addon is not created when Auto Mode is disabled
  assert {
    condition     = !contains(keys(module.eks["auto_mode_false"].eks_addon.after_compute), "metrics-server")
    error_message = "EKS Auto Mode should not create metrics-server addon when disabled"
  }

  # Test that Auto Mode controller policy is not created when auto mode is disabled
  assert {
    condition     = length(module.eks["auto_mode_false"].automode_controller_policy) == 0
    error_message = "Auto Mode controller policy should not be created when auto mode is disabled"
  }

  # Test that Auto Mode controller policy attachment is not created when auto mode is disabled
  assert {
    condition     = length(module.eks["auto_mode_false"].automode_controller_policy_attachments) == 0
    error_message = "Auto Mode controller policy attachment should not be created when auto mode is disabled"
  }

  # Test that Auto Mode policies are not attached when auto mode is disabled
  assert {
    condition     = !alltrue([for item in ["AmazonEKSBlockStoragePolicy", "AmazonEKSComputePolicy", "AmazonEKSLoadBalancingPolicy"] : contains(keys(module.eks["auto_mode_false"].eks_role_policy_attachments), item)])
    error_message = "Auto Mode specific policies should not be attached when auto mode is disabled"
  }

  expect_failures = [check.deletion_due_time]
}

run "eks_auto_mode_with_metrics_addon" {
  command = plan

  # Test that metrics-server manifest deployment is NOT created when metrics-server addon is explicitly configured
  assert {
    condition     = length(module.eks["auto_mode_with_metrics_addon"].apply_metrics_server_addon) == 0
    error_message = "EKS Auto Mode should not deploy metrics-server via manifest when metrics-server addon is explicitly configured"
  }

  # Test that metrics-server addon IS created when explicitly configured in eks_addons
  assert {
    condition     = contains(keys(module.eks["auto_mode_with_metrics_addon"].eks_addon.after_compute), "metrics-server")
    error_message = "EKS Auto Mode should create metrics-server addon when explicitly configured in eks_addons"
  }

  expect_failures = [check.deletion_due_time]
}
