variables {
  scenario_type  = "perf-eval"
  scenario_name  = "launch_template_test"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    "run_id" : "123456789",
    "region" : "us-east-1",
    "creation_time" : timestamp(),
    "ena_express" : null
  }

  network_config_list = [
    {
      role           = "lt-test"
      vpc_name       = "lt-test-vpc"
      vpc_cidr_block = "10.0.0.0/16"
      subnet = [
        {
          name                    = "lt-test-subnet"
          cidr_block              = "10.0.32.0/19"
          zone_suffix             = "a"
          map_public_ip_on_launch = true
        }
      ]
      security_group_name = "lt-test-sg"
      route_tables = [
        {
          name       = "internet-rt"
          cidr_block = "0.0.0.0/0"
        }
      ],
      route_table_associations = [
        {
          name             = "lt-test-subnet-rt-assoc"
          subnet_name      = "lt-test-subnet"
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
    role        = "lt-test"
    eks_name    = "eks_launch_template_test"
    vpc_name    = "lt-test-vpc"
    policy_arns = ["AmazonEKS_CNI_Policy"]
    eks_managed_node_groups = [{
      # Node group with explicit network interfaces configuration
      name           = "ng-with-network-interfaces"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 1
      max_size       = 3
      desired_size   = 2
      ena_express    = true
      network_interfaces = {
        associate_public_ip_address = true
        delete_on_termination       = true
        interface_type              = "efa"
      }
      block_device_mappings = [{
        device_name = "/dev/xvda"
        ebs = {
          delete_on_termination = true
          volume_size           = 100
          volume_type           = "gp3"
        }
      }]
      }, {
      # Node group with ENA Express but no explicit network interfaces
      name           = "ng-ena-express-only"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 1
      max_size       = 3
      desired_size   = 1
      ena_express    = true
      block_device_mappings = [{
        device_name = "/dev/xvda"
        ebs = {
          delete_on_termination = true
          volume_size           = 100
          volume_type           = "gp3"
        }
      }]
      }, {
      # Node group with capacity reservation
      name           = "ng-with-capacity-reservation"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      capacity_type  = "CAPACITY_BLOCK"
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      capacity_reservation_specification = {
        capacity_reservation_preference = "capacity-reservations-only"
        capacity_reservation_target = {
          capacity_reservation_id = "cr-0123456789abcdef0"
        }
      }
      block_device_mappings = [{
        device_name = "/dev/xvda"
        ebs = {
          delete_on_termination = true
          volume_size           = 100
          volume_type           = "gp3"
        }
      }]
      }, {
      # Node group with capacity reservation but no id
      name           = "ng-with-capacity-reservation-no-id"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      capacity_type  = "CAPACITY_BLOCK"
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      capacity_reservation_specification = {
        capacity_reservation_preference = "capacity-reservations-only"
      }
      }, {
      # Node group with spot instances
      name           = "ng-with-spot-instances"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 1
      max_size       = 5
      desired_size   = 2
      instance_market_options = {
        market_type = "spot"
        spot_options = {
          instance_interruption_behavior = "terminate"
          max_price                      = "0.05"
          spot_instance_type             = "one-time"
        }
      }
      block_device_mappings = [{
        device_name = "/dev/xvda"
        ebs = {
          delete_on_termination = true
          volume_size           = 100
          volume_type           = "gp3"
        }
      }]
      }, {
      # Node group without any special configurations (baseline)
      name           = "ng-baseline"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      block_device_mappings = [{
        device_name = "/dev/xvda"
        ebs = {
          delete_on_termination = true
          volume_size           = 100
          volume_type           = "gp3"
        }
      }]
    }]
    eks_addons = []
  }]
}

# Test network interfaces configuration - focus on static attributes
run "network_interfaces_with_ena_express" {
  command = plan

  # Verify that launch template is created for this node group
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"] != null
    error_message = "Expected launch template to be created for ng-with-network-interfaces"
  }

  # Verify block device mappings configuration (static)
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].block_device_mappings) == 1
    error_message = "Expected one block device mapping"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].block_device_mappings[0].device_name == "/dev/xvda"
    error_message = "Expected device_name to be /dev/xvda"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].block_device_mappings[0].ebs[0].volume_size == 100
    error_message = "Expected volume_size to be 100"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].block_device_mappings[0].ebs[0].volume_type == "gp3"
    error_message = "Expected volume_type to be gp3"
  }
}

# Test ENA Express without explicit network interfaces - focus on static config
run "ena_express_without_network_interfaces" {
  command = plan

  # Verify that launch template is created
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-ena-express-only"] != null
    error_message = "Expected launch template to be created for ng-ena-express-only"
  }

  # Test static EKS node group configuration
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups["ng-ena-express-only"].ami_type == "AL2023_x86_64_STANDARD"
    error_message = "Expected ami_type to be AL2023_x86_64_STANDARD"
  }

  # Test scaling configuration
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups["ng-ena-express-only"].scaling_config[0].min_size == 1
    error_message = "Expected min_size to be 1"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups["ng-ena-express-only"].scaling_config[0].max_size == 3
    error_message = "Expected max_size to be 3"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups["ng-ena-express-only"].scaling_config[0].desired_size == 1
    error_message = "Expected desired_size to be 1"
  }
}

# Test capacity reservation specification
run "capacity_reservation_specification" {
  command = plan

  # Verify capacity reservation block is created
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation"].capacity_reservation_specification) == 1
    error_message = "Expected capacity_reservation_specification block to be created"
  }

  # Verify capacity reservation preference
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation"].capacity_reservation_specification[0].capacity_reservation_preference == "capacity-reservations-only"
    error_message = "Expected capacity_reservation_preference to be 'capacity-reservations-only'"
  }

  # Verify capacity reservation target
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation"].capacity_reservation_specification[0].capacity_reservation_target) == 1
    error_message = "Expected capacity_reservation_target block to be created"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation"].capacity_reservation_specification[0].capacity_reservation_target[0].capacity_reservation_id == "cr-0123456789abcdef0"
    error_message = "Expected capacity_reservation_id to match"
  }

  # Verify instance type is set for capacity block
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation"].instance_type == "m5.large"
    error_message = "Expected instance_type to be set for CAPACITY_BLOCK"
  }
}

# Test instance market options (spot instances)
run "instance_market_options_spot" {
  command = plan

  # Verify instance market options block is created
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-spot-instances"].instance_market_options) == 1
    error_message = "Expected instance_market_options block to be created"
  }

  # Verify market type
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-spot-instances"].instance_market_options[0].market_type == "spot"
    error_message = "Expected market_type to be 'spot'"
  }

  # Verify spot options block is created
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-spot-instances"].instance_market_options[0].spot_options) == 1
    error_message = "Expected spot_options block to be created"
  }

  # Verify spot options configuration
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-spot-instances"].instance_market_options[0].spot_options[0].instance_interruption_behavior == "terminate"
    error_message = "Expected instance_interruption_behavior to be 'terminate'"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-spot-instances"].instance_market_options[0].spot_options[0].max_price == "0.05"
    error_message = "Expected max_price to be '0.05'"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-spot-instances"].instance_market_options[0].spot_options[0].spot_instance_type == "one-time"
    error_message = "Expected spot_instance_type to be 'one-time'"
  }
}

# Test baseline node group (no special configurations) - focus on EKS node group attributes
run "baseline_node_group_no_special_configs" {
  command = plan

  # Verify that launch template is created
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"] != null
    error_message = "Expected launch template to be created for ng-baseline"
  }

  # Test that baseline node group has expected configuration
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups["ng-baseline"].capacity_type == "ON_DEMAND"
    error_message = "Expected capacity_type to be ON_DEMAND for baseline node group"
  }

  # Test scaling configuration
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups["ng-baseline"].scaling_config[0].min_size == 1
    error_message = "Expected min_size to be 1"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups["ng-baseline"].scaling_config[0].max_size == 2
    error_message = "Expected max_size to be 2"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups["ng-baseline"].scaling_config[0].desired_size == 1
    error_message = "Expected desired_size to be 1"
  }

  # Test instance types - verify it contains m5.large
  assert {
    condition     = contains(module.eks["eks_launch_template_test"].eks_node_groups["ng-baseline"].instance_types, "m5.large")
    error_message = "Expected instance_types to contain m5.large"
  }
}

# Test global ENA Express setting - focus on configuration validation
run "global_ena_express_setting" {
  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "us-east-1",
      "creation_time" : timestamp(),
      "ena_express" : true
    }
  }

  command = plan

  # Verify that launch template is created with global ENA Express setting
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"] != null
    error_message = "Expected launch template to be created for ng-baseline with global ena_express"
  }

  # Test that the baseline node group still has expected basic configuration
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups["ng-baseline"].ami_type == "AL2023_x86_64_STANDARD"
    error_message = "Expected ami_type to be AL2023_x86_64_STANDARD"
  }

  # Test block device mapping is still configured
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"].block_device_mappings) == 1
    error_message = "Expected one block device mapping"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"].block_device_mappings[0].device_name == "/dev/xvda"
    error_message = "Expected device_name to be /dev/xvda"
  }
}

# Test global capacity_reservation_id setting that overrides node group configuration
run "global_capacity_reservation_id_override" {
  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "us-east-1",
      "creation_time" : timestamp(),
      "capacity_reservation_id" : "cr-global-override-12345"
    }
  }

  command = plan

  # Verify that global capacity_reservation_id overrides the node group setting
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation"].capacity_reservation_specification[0].capacity_reservation_target[0].capacity_reservation_id == "cr-global-override-12345"
    error_message = "Expected global capacity_reservation_id to override node group configuration"
  }

  # Verify that the capacity reservation preference is still respected from node group config
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation"].capacity_reservation_specification[0].capacity_reservation_preference == "capacity-reservations-only"
    error_message = "Expected capacity_reservation_preference to remain from node group config"
  }

  # Verify that resource group ARN is still null (not affected by global override)
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation"].capacity_reservation_specification[0].capacity_reservation_target[0].capacity_reservation_resource_group_arn == null
    error_message = "Expected capacity_reservation_resource_group_arn to remain null"
  }
}

# Test global capacity_reservation_id setting that overrides node group configuration
run "global_capacity_reservation_id_override_for_no_id" {
  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "us-east-1",
      "creation_time" : timestamp(),
      "capacity_reservation_id" : "cr-global-override-12345"
    }
  }

  command = plan

  # Verify that global capacity_reservation_id overrides the node group setting
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation-no-id"].capacity_reservation_specification[0].capacity_reservation_target[0].capacity_reservation_id == "cr-global-override-12345"
    error_message = "Expected global capacity_reservation_id to override node group configuration"
  }

  # Verify that the capacity reservation preference is still respected from node group config
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation-no-id"].capacity_reservation_specification[0].capacity_reservation_preference == "capacity-reservations-only"
    error_message = "Expected capacity_reservation_preference to remain from node group config"
  }

  # Verify that resource group ARN is still null (not affected by global override)
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-capacity-reservation-no-id"].capacity_reservation_specification[0].capacity_reservation_target[0].capacity_reservation_resource_group_arn == null
    error_message = "Expected capacity_reservation_resource_group_arn to remain null"
  }
}
