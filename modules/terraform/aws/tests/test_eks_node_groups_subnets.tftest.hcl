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
          name                    = "nap-subnet-1"
          cidr_block              = "10.0.32.0/19"
          zone_suffix             = "a"
          map_public_ip_on_launch = true
        },
        {
          name                    = "nap-subnet-2"
          cidr_block              = "10.0.64.0/19"
          zone_suffix             = "b"
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
          subnet_name      = "nap-subnet-1"
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
    eks_name    = "eks_name"
    vpc_name    = "nap-vpc"
    policy_arns = ["AmazonEKS_CNI_Policy"]
    eks_managed_node_groups = [
      {
        name           = "default"
        ami_type       = "AL2023_x86_64_STANDARD"
        instance_types = ["m4.large"]
        min_size       = 1
        max_size       = 2
        desired_size   = 1
      },
      {
        name           = "userpool"
        ami_type       = "AL2023_x86_64_STANDARD"
        instance_types = ["m4.large"]
        min_size       = 5
        max_size       = 5
        desired_size   = 5
        subnet_names   = ["nap-subnet-1"]
    }]
    eks_addons = []
  }]
}

mock_provider "aws" {
  source = "./tests"
}

override_data {
  target = module.eks["eks_name"].data.aws_subnets.subnets
  values = { ids = ["nap-subnet-1-id", "nap-subnet-2-id"] }
}

override_data {
  target = module.eks["eks_name"].data.aws_subnet.subnet_details["nap-subnet-1"]
  values = { id = "nap-subnet-1-id" }
}


run "valid_eks_nodes_subnet" {

  command = apply

  # Expected all cluster's subnet_ids
  assert {
    condition     = tolist(module.eks["eks_name"].eks_node_groups["default"].subnet_ids) == tolist(["nap-subnet-1-id", "nap-subnet-2-id"])
    error_message = "Expected: ['nap-subnet-1', 'nap-subnet-2'] \n Actual:  ${jsonencode(module.eks["eks_name"].eks_node_groups["default"].subnet_ids)}"
  }

  # Expected only the subnet_id of the subnet defined in the node group
  assert {
    condition     = tolist(module.eks["eks_name"].eks_node_groups["userpool"].subnet_ids) == tolist(["nap-subnet-1-id"])
    error_message = "Expected: ['nap-subnet-1'] \n Actual:  ${jsonencode(module.eks["eks_name"].eks_node_groups["userpool"].subnet_ids)}"
  }

  expect_failures = [check.deletion_due_time]
}
