scenario_name  = "perf_eval_vm_aws"
deletion_delay = "2h"
network_config_list = [
  {
    role                   = "network"
    vpc_name               = "same-vpc"
    vpc_cidr_block         = "10.2.0.0/16"
    subnet_names           = ["same-subnet"]
    subnet_cidr_block      = ["10.2.1.0/24"]
    security_group_name    = "same-sg"
    route_table_cidr_block = "0.0.0.0/0"
    sg_rules = {
      ingress = [
        {
          from_port  = 2222
          to_port    = 2222
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 20001
          to_port    = 20001
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 20002
          to_port    = 20002
          protocol   = "udp"
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
vm_config_list = [{
    vm_name                     = "client-vm"
    role                        = "client"
    subnet_name                 = "same-subnet"
    security_group_name         = "same-sg"
    associate_public_ip_address = true
  },
  {
    vm_name                     = "server-vm"
    role                        = "server"
    subnet_name                 = "same-subnet"
    security_group_name         = "same-sg"
    associate_public_ip_address = true
  }
]
