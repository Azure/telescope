scenario_type  = "perf-eval"
scenario_name  = "vm-diff-zone-iperf"
deletion_delay = "2h"
network_config_list = [
  {
    role           = "network"
    vpc_name       = "us-east-2-vpc"
    vpc_cidr_block = "10.2.0.0/16"
    subnet = [
      {
        name        = "us-east-2-client-subnet"
        cidr_block  = "10.2.1.0/24"
        zone_suffix = "a"
      }
    ]
    security_group_name    = "us-east-2-sg"
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
  subnet_name                 = "us-east-2-client-subnet"
  security_group_name         = "us-east-2-sg"
  associate_public_ip_address = true
  zone_suffix                 = "a"
  }
]