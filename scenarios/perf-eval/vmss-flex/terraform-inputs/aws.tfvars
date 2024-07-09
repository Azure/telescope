scenario_type  = "perf-eval"
scenario_name  = "vmss-flex-scale"
deletion_delay = "2h"
network_config_list = [
  {
    role                = "network"
    vpc_name            = "vmss-flex-scale-vpc"
    vpc_cidr_block      = "10.2.0.0/16"
    security_group_name = "vmss-flex-scale-sg"
    subnet = [{
      name        = "vmss-flex-scale-subnet"
      cidr_block  = "10.2.1.0/21"
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
