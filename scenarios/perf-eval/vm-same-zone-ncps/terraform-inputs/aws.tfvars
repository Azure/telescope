scenario_type  = "perf-eval"
scenario_name  = "vm-same-zone-ncps"
deletion_delay = "2h"
network_config_list = [
  {
    role           = "network"
    vpc_name       = "same-vpc"
    vpc_cidr_block = "10.2.0.0/16"
    subnet = [{
      name        = "same-subnet"
      cidr_block  = "10.2.1.0/24"
      zone_suffix = "c"
    }]
    security_group_name = "same-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "same-subnet-rt-assoc"
        subnet_name      = "same-subnet"
        route_table_name = "internet-rt"
      }
    ]
    sg_rules = {
      ingress = [
        {
          from_port  = 0
          to_port    = 65535
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
  },
]
loadbalancer_config_list = []
vm_config_list = [
  {
    vm_name                     = "client-vm"
    role                        = "client"
    subnet_name                 = "same-subnet"
    security_group_name         = "same-sg"
    associate_public_ip_address = true
    zone_suffix                 = "c"
  },
  {
    vm_name                     = "server-vm"
    role                        = "server"
    subnet_name                 = "same-subnet"
    security_group_name         = "same-sg"
    associate_public_ip_address = true
    zone_suffix                 = "c"
  }
]