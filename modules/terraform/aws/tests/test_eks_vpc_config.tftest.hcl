
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
      role           = "nap"
      vpc_name       = "nap-vpc"
      vpc_cidr_block = "10.0.0.0/16"
      subnet = [
        {
          name                    = "nap-subnet"
          cidr_block              = "10.0.32.0/19"
          zone_suffix             = "a"
          map_public_ip_on_launch = true
        }
      ]
      security_group_name = "nap-sg"
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
}

run "valid_vpc_config_default" {

  command = plan

  variables {
    eks_config_list = [{
      role        = "nap"
      eks_name    = "eks_name"
      vpc_name    = "nap-vpc"
      policy_arns = ["AmazonEKS_CNI_Policy"]
      eks_managed_node_groups = [
        {
          name           = "my_scenario-ng"
          ami_type       = "AL2023_x86_64_STANDARD"
          instance_types = ["m4.large"]
          min_size       = 5
          max_size       = 5
          desired_size   = 5
        }
      ]
      eks_addons = [{ name = "vpc-cni" }]
    }]
  }

  assert {
    condition     = jsondecode(module.eks["eks_name"].eks_addon.before_compute.vpc-cni.configuration_values).env.ENABLE_PREFIX_DELEGATION == "true"
    error_message = "Error ENABLE_PREFIX_DELEGATION expected value: 'true'"
  }

  assert {
    condition     = jsondecode(module.eks["eks_name"].eks_addon.before_compute.vpc-cni.configuration_values).env.WARM_PREFIX_TARGET == "1"
    error_message = "Error WARM_PREFIX_TARGET expected value: '1'"
  }

  expect_failures = [check.deletion_due_time]

}

run "valid_vpc_config_set" {

  command = plan

  variables {
    eks_config_list = [{
      role        = "nap"
      eks_name    = "eks_name"
      vpc_name    = "nap-vpc"
      policy_arns = ["AmazonEKS_CNI_Policy"]
      eks_managed_node_groups = [
        {
          name           = "my_scenario-ng"
          ami_type       = "AL2023_x86_64_STANDARD"
          instance_types = ["m5a.xlarge"]
          min_size       = 5
          max_size       = 5
          desired_size   = 5
        }
      ]
      eks_addons = [{
        name                       = "vpc-cni"
        vpc_cni_warm_prefix_target = 4
      }]
    }]
  }

  assert {
    condition     = jsondecode(module.eks["eks_name"].eks_addon.before_compute.vpc-cni.configuration_values).env.ENABLE_PREFIX_DELEGATION == "true"
    error_message = "Error ENABLE_PREFIX_DELEGATION expected value: 'true'"
  }

  assert {
    condition     = jsondecode(module.eks["eks_name"].eks_addon.before_compute.vpc-cni.configuration_values).env.WARM_PREFIX_TARGET == "4"
    error_message = "Error WARM_PREFIX_TARGET expected value: '1'"
  }

  expect_failures = [check.deletion_due_time]
}

run "valid_karpenter_set" {

  command = plan

  variables {
    eks_config_list = [{
      role        = "nap"
      eks_name    = "eks_name"
      vpc_name    = "nap-vpc"
      policy_arns = ["AmazonEKS_CNI_Policy"]
      eks_managed_node_groups = [
        {
          name           = "my_scenario-ng"
          ami_type       = "AL2023_x86_64_STANDARD"
          instance_types = ["m5a.xlarge"]
          min_size       = 5
          max_size       = 5
          desired_size   = 5
        }
      ]
      enable_karpenter = true
      eks_addons       = []
    }]
  }

  assert {
    condition     = jsondecode(module.eks["eks_name"].eks_addon.before_compute.vpc-cni.configuration_values).env.ENABLE_PREFIX_DELEGATION == "true"
    error_message = "Error ENABLE_PREFIX_DELEGATION expected value: 'true'"
  }

  assert {
    condition     = jsondecode(module.eks["eks_name"].eks_addon.before_compute.vpc-cni.configuration_values).env.WARM_PREFIX_TARGET == "1"
    error_message = "Error WARM_PREFIX_TARGET expected value: '1'"
  }

  expect_failures = [check.deletion_due_time]
}

run "valid_add_after_before_compute" {

  command = plan

  variables {
    eks_config_list = [{
      role        = "nap"
      eks_name    = "eks_name"
      vpc_name    = "nap-vpc"
      policy_arns = ["AmazonEKS_CNI_Policy"]
      eks_managed_node_groups = [
        {
          name           = "my_scenario-ng"
          ami_type       = "AL2023_x86_64_STANDARD"
          instance_types = ["m5a.xlarge"]
          min_size       = 5
          max_size       = 5
          desired_size   = 5
        }
      ]
      eks_addons = [
        {
          name = "addon_after_compute_default"
        },
        {
          name           = "addon_before_compute"
          before_compute = true
        }
      ]
    }]
  }

  assert {
    condition     = contains(keys(module.eks["eks_name"].eks_addon.after_compute), "addon_after_compute_default")
    error_message = "Error addon should be created after compute"
  }

  assert {
    condition     = contains(keys(module.eks["eks_name"].eks_addon.before_compute), "addon_before_compute")
    error_message = "Error addon should be created before compute"
  }

  expect_failures = [check.deletion_due_time]
}