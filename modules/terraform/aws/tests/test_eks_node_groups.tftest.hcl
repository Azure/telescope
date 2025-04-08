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

  eks_config_list = [{
    role        = "nap"
    eks_name    = "eks_name"
    vpc_name    = "nap-vpc"
    policy_arns = ["AmazonEKS_CNI_Policy"]
    eks_managed_node_groups = [{
        name           = "my_scenario-ng"
        ami_type       = "AL2_x86_64"
        instance_types = ["m4.large"]
        min_size       = 5
        max_size       = 5
        desired_size   = 5
      }, {
      name           = "my_scenario-ng-2"
      ami_type       = "AL2_x86_64"
      instance_types = ["m4.large"]
      min_size       = 5
      max_size       = 5
      desired_size   = 5
      ena_express    = true
    }]
    eks_addons = []
  }]
}

run "valid_launch_template_required_tags" {

  command = plan

  assert {
    condition     = module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng"].tag_specifications[0].tags.owner == var.owner
    error_message = "Error. Expected owner ('${var.owner}') in the launch template tag specifications"
  }

  assert {
    condition     = module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng"].tag_specifications[0].tags.deletion_due_time == timeadd(var.json_input.creation_time, var.deletion_delay)
    error_message = "Error. Expected deletion_due_time in the launch template tag specifications"
  }

  expect_failures = [check.deletion_due_time]
}

run "valid_launch_template_name" {

  command = plan

  assert {
    condition     = strcontains(module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng"].name, var.json_input.run_id)
    error_message = "Error. Launch tempalte name must be unique (expected to contain run id: ${var.json_input.run_id})"
  }

  expect_failures = [check.deletion_due_time]
}

run "valid_launch_template_ena_express" {

  command = plan

  # ena express null
  assert {
    condition     = length(module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng"].network_interfaces[0].ena_srd_specification) == 0
    error_message = "Error. Expected ena_srd_enabled false in the launch template ena srd specification"
  }

  # ena express enabled
  assert {
    condition     = module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng-2"].network_interfaces[0].ena_srd_specification[0].ena_srd_enabled == true
    error_message = "Error. Expected ena_srd_enabled true in the launch template ena srd specification"
  }

  assert {
    condition     = module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng-2"].network_interfaces[0].ena_srd_specification[0].ena_srd_udp_specification[0].ena_srd_udp_enabled == true
    error_message = "Error. Expected ena_srd_udp_enabled true in the launch template ena srd specification"
  }

  expect_failures = [check.deletion_due_time]
}

run "valid_launch_template_ena_express_override" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "us-east-1",
      "creation_time" : "2024-11-12T16:39:54Z"
      "ena_express" : true
    }
  }

  # ena express enabled
  assert {
    condition     = module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng"].network_interfaces[0].ena_srd_specification[0].ena_srd_enabled == true
    error_message = "Error. Expected ena_srd_enabled true in the launch template ena srd specification"
  }

  assert {
    condition     = module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng"].network_interfaces[0].ena_srd_specification[0].ena_srd_udp_specification[0].ena_srd_udp_enabled == true
    error_message = "Error. Expected ena_srd_udp_enabled true in the launch template ena srd specification"
  }

  assert {
    condition     = module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng-2"].network_interfaces[0].ena_srd_specification[0].ena_srd_enabled == true
    error_message = "Error. Expected ena_srd_enabled true in the launch template ena srd specification"
  }

  assert {
    condition     = module.eks["eks_name"].eks_node_groups_launch_template["my_scenario-ng-2"].network_interfaces[0].ena_srd_specification[0].ena_srd_udp_specification[0].ena_srd_udp_enabled == true
    error_message = "Error. Expected ena_srd_udp_enabled true in the launch template ena srd specification"
  }

  expect_failures = [check.deletion_due_time]
}