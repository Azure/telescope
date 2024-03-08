scenario_type  = "perf-eval"
scenario_name  = "create-delete-vm"
deletion_delay = "2h"
network_config_list = [
  {
    role                = "network"
    vpc_name            = "create-delete-vm-vpc"
    vpc_cidr_block      = "10.2.0.0/16"
    security_group_name = "create-delete-vm-sg"
    subnet = [{
      name        = "create-delete-vm-subnet"
      cidr_block  = "10.2.1.0/24"
      zone_suffix = "a"
    }]
    route_tables             = []
    route_table_associations = []
    sg_rules = {
      ingress = []
      egress  = []
    }
  }
]
