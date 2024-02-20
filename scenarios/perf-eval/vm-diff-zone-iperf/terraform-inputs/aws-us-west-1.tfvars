scenario_type  = "perf-eval"
scenario_name  = "vm-diff-zone-iperf"
deletion_delay = "2h"
network_config_list = [
  {
    role           = "network"
    vpc_name       = "us-west-1-vpc"
    vpc_cidr_block = "10.2.0.0/16"
    subnet = [
      {
        name        = "us-west-1-server-subnet"
        cidr_block  = "10.2.2.0/24"
        zone_suffix = "b"
      },
      {
        name        = "us-west-1-client-subnet"
        cidr_block  = "10.2.1.0/24"
        zone_suffix = "a"
      }
    ]
    security_group_name    = "us-west-1-sg"
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
vm_config_list = [
  {
    vm_name                     = "server-vm"
    role                        = "server"
    subnet_name                 = "us-west-1-server-subnet"
    security_group_name         = "us-west-1-sg"
    associate_public_ip_address = true
    zone_suffix                 = "b"
  },
  {
    vm_name                     = "client-vm"
    role                        = "client"
    subnet_name                 = "us-west-1-client-subnet"
    security_group_name         = "us-west-1-sg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  }
]
