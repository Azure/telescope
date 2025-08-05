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

# Test network interfaces configuration
run "network_interfaces_with_ena_express" {
  command = plan

  # Verify that network interfaces block is created when explicitly configured
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].network_interfaces) == 1
    error_message = "Expected network_interfaces block to be created for ng-with-network-interfaces"
  }

  # Verify ENA Express is enabled in network interfaces
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].network_interfaces[0].ena_srd_specification[0].ena_srd_enabled == true
    error_message = "Expected ENA Express to be enabled in network interfaces"
  }

  # Verify UDP specification is enabled
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].network_interfaces[0].ena_srd_specification[0].ena_srd_udp_specification[0].ena_srd_udp_enabled == true
    error_message = "Expected ENA Express UDP to be enabled"
  }

  # Verify network interface properties are correctly set
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].network_interfaces[0].associate_public_ip_address == "true"
    error_message = "Expected associate_public_ip_address to be true"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].network_interfaces[0].delete_on_termination == "true"
    error_message = "Expected delete_on_termination to be true"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-with-network-interfaces"].network_interfaces[0].interface_type == "efa"
    error_message = "Expected interface_type to be efa"
  }
}

# Test ENA Express without explicit network interfaces
run "ena_express_without_network_interfaces" {
  command = plan

  # Verify that network interfaces block is created even without explicit configuration when ENA Express is enabled
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-ena-express-only"].network_interfaces) == 1
    error_message = "Expected network_interfaces block to be created for ENA Express even without explicit network_interfaces config"
  }

  # Verify ENA Express is enabled
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-ena-express-only"].network_interfaces[0].ena_srd_specification[0].ena_srd_enabled == true
    error_message = "Expected ENA Express to be enabled"
  }

  # Verify that network interface properties are null when not explicitly configured
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-ena-express-only"].network_interfaces[0].associate_public_ip_address == null
    error_message = "Expected associate_public_ip_address to be null when not configured"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-ena-express-only"].network_interfaces[0].delete_on_termination == null
    error_message = "Expected delete_on_termination to be null when not configured"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-ena-express-only"].network_interfaces[0].interface_type == null
    error_message = "Expected interface_type to be null when not configured"
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

# Test baseline node group (no special configurations)
run "baseline_node_group_no_special_configs" {
  command = plan

  # Verify that network interfaces block is NOT created when not needed
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"].network_interfaces) == 0
    error_message = "Expected no network_interfaces block for baseline node group"
  }

  # Verify that capacity reservation block is NOT created
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"].capacity_reservation_specification) == 0
    error_message = "Expected no capacity_reservation_specification block for baseline node group"
  }

  # Verify that instance market options block is NOT created
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"].instance_market_options) == 0
    error_message = "Expected no instance_market_options block for baseline node group"
  }

  # Verify instance type is null for non-capacity-block
  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"].instance_type == null
    error_message = "Expected instance_type to be null for non-CAPACITY_BLOCK"
  }
}

# Test global ENA Express setting
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

  # Verify that global ENA Express setting affects baseline node group
  assert {
    condition     = length(module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"].network_interfaces) == 1
    error_message = "Expected network_interfaces block to be created when global ena_express is true"
  }

  assert {
    condition     = module.eks["eks_launch_template_test"].eks_node_groups_launch_template["ng-baseline"].network_interfaces[0].ena_srd_specification[0].ena_srd_enabled == true
    error_message = "Expected ENA Express to be enabled via global setting"
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