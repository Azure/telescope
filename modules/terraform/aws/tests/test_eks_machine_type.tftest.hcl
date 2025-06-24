variables {
  scenario_type  = "perf-eval"
  scenario_name  = "my_scenario"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    "run_id" : "123456789",
    "region" : "us-east-1",
    "creation_time" : "2024-11-12T16:39:54Z"
    "k8s_machine_type" : "m4x.4large"
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
    }]
    eks_addons = []
  }]
}

run "valid_eks_machine_type_override_all" {

  command = plan

  assert {
    condition     = module.eks["eks_name"].eks_node_groups["default"].instance_types[0] == var.json_input["k8s_machine_type"]
    error_message = "Expected: ${var.json_input["k8s_machine_type"]} \n Actual:  ${module.eks["eks_name"].eks_node_groups["default"].instance_types[0]}"
  }

  assert {
    condition     = module.eks["eks_name"].eks_node_groups["userpool"].instance_types[0] == var.json_input["k8s_machine_type"]
    error_message = "Expected: ${var.json_input["k8s_machine_type"]} \n Actual:  ${module.eks["eks_name"].eks_node_groups["userpool"].instance_types[0]}"
  }

  expect_failures = [check.deletion_due_time]
}

run "valid_eks_machine_type_no_override" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "us-east-1",
      "creation_time" : "2024-11-12T16:39:54Z"
    }
  }

  assert {
    condition     = module.eks["eks_name"].eks_node_groups["default"].instance_types[0] == var.eks_config_list[0].eks_managed_node_groups[0].instance_types[0]
    error_message = "Expected: ${var.eks_config_list[0].eks_managed_node_groups[0].instance_types[0]} \n Actual: ${module.eks["eks_name"].eks_node_groups["default"].instance_types[0]}"
  }

  assert {
    condition     = module.eks["eks_name"].eks_node_groups["userpool"].instance_types[0] == var.eks_config_list[0].eks_managed_node_groups[0].instance_types[0]
    error_message = "Expected: ${var.eks_config_list[0].eks_managed_node_groups[0].instance_types[0]} \n Actual: ${module.eks["eks_name"].eks_node_groups["userpool"].instance_types[0]}"
  }

  expect_failures = [check.deletion_due_time]
}



