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
    route_tables = [
      {
        name       = "create-delete-vm-rt"
        cidr_block = "0.0.0.0/0"
      }
    ]
    route_table_associations = [
      {
        name             = "create-delete-vm-rt-assoc"
        subnet_name      = "create-delete-vm-subnet"
        route_table_name = "create-delete-vm-rt"
      }
    ]
    sg_rules = {
      ingress = [
        {
          from_port  = 22
          to_port    = 22
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 3389
          to_port    = 3389
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        }
      ]
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
