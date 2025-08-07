variables {
  scenario_type  = "perf-eval"
  scenario_name  = "launch_template_edge_cases"
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
      role           = "edge-test"
      vpc_name       = "edge-test-vpc"
      vpc_cidr_block = "10.0.0.0/16"
      subnet = [
        {
          name                    = "edge-test-subnet"
          cidr_block              = "10.0.32.0/19"
          zone_suffix             = "a"
          map_public_ip_on_launch = true
        }
      ]
      security_group_name = "edge-test-sg"
      route_tables = [
        {
          name       = "internet-rt"
          cidr_block = "0.0.0.0/0"
        }
      ],
      route_table_associations = [
        {
          name             = "edge-test-subnet-rt-assoc"
          subnet_name      = "edge-test-subnet"
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
    role        = "edge-test"
    eks_name    = "eks_edge_test"
    vpc_name    = "edge-test-vpc"
    policy_arns = ["AmazonEKS_CNI_Policy"]
    eks_managed_node_groups = [{
      # Test complex capacity reservation with resource group ARN
      name           = "ng-capacity-with-resource-group"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      capacity_type  = "CAPACITY_BLOCK"
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      capacity_reservation_specification = {
        capacity_reservation_preference = "capacity-reservations-only"
        capacity_reservation_target = {
          capacity_reservation_resource_group_arn = "arn:aws:resource-groups:us-east-1:123456789012:group/my-resource-group"
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
      # Test capacity reservation with open preference
      name           = "ng-capacity-open"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      capacity_reservation_specification = {
        capacity_reservation_preference = "open"
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
      # Test spot instance with all options
      name           = "ng-spot-full-config"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 1
      max_size       = 5
      desired_size   = 2
      instance_market_options = {
        market_type = "spot"
        spot_options = {
          block_duration_minutes         = 60
          instance_interruption_behavior = "hibernate"
          max_price                      = "0.10"
          spot_instance_type             = "persistent"
          valid_until                    = "2024-12-31T23:59:59Z"
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
      # Test ENA Express false (explicitly disabled)
      name           = "ng-ena-express-disabled"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      ena_express    = false
      network_interfaces = {
        associate_public_ip_address = false
        delete_on_termination       = true
        interface_type              = "interface"
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
      # Test partial network interfaces config
      name           = "ng-partial-network-config"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m5.large"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
      network_interfaces = {
        associate_public_ip_address = true
        # delete_on_termination and interface_type intentionally omitted
      }
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

# Test capacity reservation with resource group ARN
run "capacity_reservation_with_resource_group" {
  command = plan

  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-capacity-with-resource-group"].capacity_reservation_specification[0].capacity_reservation_target[0].capacity_reservation_resource_group_arn == "arn:aws:resource-groups:us-east-1:123456789012:group/my-resource-group"
    error_message = "Expected capacity_reservation_resource_group_arn to match"
  }

  # Verify capacity_reservation_id is null when using resource group
  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-capacity-with-resource-group"].capacity_reservation_specification[0].capacity_reservation_target[0].capacity_reservation_id == null
    error_message = "Expected capacity_reservation_id to be null when using resource group ARN"
  }
}

# Test capacity reservation with open preference (no target)
run "capacity_reservation_open_preference" {
  command = plan

  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-capacity-open"].capacity_reservation_specification[0].capacity_reservation_preference == "open"
    error_message = "Expected capacity_reservation_preference to be 'open'"
  }

  # Verify no capacity reservation target when preference is open
  assert {
    condition     = length(module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-capacity-open"].capacity_reservation_specification[0].capacity_reservation_target) == 0
    error_message = "Expected no capacity_reservation_target for open preference"
  }
}

# Test spot instance with full configuration
run "spot_instance_full_configuration" {
  command = plan

  # Verify all spot options are correctly set
  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-spot-full-config"].instance_market_options[0].spot_options[0].block_duration_minutes == 60
    error_message = "Expected block_duration_minutes to be 60"
  }

  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-spot-full-config"].instance_market_options[0].spot_options[0].instance_interruption_behavior == "hibernate"
    error_message = "Expected instance_interruption_behavior to be 'hibernate'"
  }

  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-spot-full-config"].instance_market_options[0].spot_options[0].max_price == "0.10"
    error_message = "Expected max_price to be '0.10'"
  }

  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-spot-full-config"].instance_market_options[0].spot_options[0].spot_instance_type == "persistent"
    error_message = "Expected spot_instance_type to be 'persistent'"
  }

  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-spot-full-config"].instance_market_options[0].spot_options[0].valid_until == "2024-12-31T23:59:59Z"
    error_message = "Expected valid_until to match"
  }
}

# Test ENA Express explicitly disabled
run "ena_express_explicitly_disabled" {
  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "us-east-1",
      "creation_time" : timestamp()
    }
    eks_config_list = [{
      role        = "edge-test"
      eks_name    = "eks_edge_test"
      vpc_name    = "edge-test-vpc"
      policy_arns = ["AmazonEKS_CNI_Policy"]
      eks_managed_node_groups = [{
        name           = "ng-ena-express-disabled"
        ami_type       = "AL2023_x86_64_STANDARD"
        instance_types = ["m5.large"]
        min_size       = 1
        max_size       = 2
        desired_size   = 1
        ena_express    = false
        network_interfaces = {
          associate_public_ip_address = false
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
      }]
      eks_addons = []
    }]
  }

  command = plan

  # Network interfaces should be created due to explicit configuration
  assert {
    condition     = length(module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-ena-express-disabled"].network_interfaces) == 1
    error_message = "Expected network_interfaces block to be created even when ENA Express is disabled"
  }

  # ENA Express should be false when explicitly set
  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-ena-express-disabled"].network_interfaces[0].ena_srd_specification[0].ena_srd_enabled == false
    error_message = "Expected ena_srd_specification to be false"
  }

  # Network interface properties should still be set
  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-ena-express-disabled"].network_interfaces[0].associate_public_ip_address == "false"
    error_message = "Expected associate_public_ip_address to be false"
  }

  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-ena-express-disabled"].network_interfaces[0].interface_type == "efa"
    error_message = "Expected interface_type to be 'efa'"
  }
}

# Test partial network interfaces configuration
run "partial_network_interfaces_config" {
  command = plan

  # Network interfaces should be created
  assert {
    condition     = length(module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-partial-network-config"].network_interfaces) == 1
    error_message = "Expected network_interfaces block to be created with partial config"
  }

  # Explicitly set property should be present
  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-partial-network-config"].network_interfaces[0].associate_public_ip_address == "true"
    error_message = "Expected associate_public_ip_address to be true"
  }

  # Omitted properties should be null
  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-partial-network-config"].network_interfaces[0].delete_on_termination == null
    error_message = "Expected delete_on_termination to be null when not specified"
  }

  assert {
    condition     = module.eks["eks_edge_test"].eks_node_groups_launch_template["ng-partial-network-config"].network_interfaces[0].interface_type == null
    error_message = "Expected interface_type to be null when not specified"
  }
}
