scenario_type  = "perf-eval"
scenario_name  = "storage-fileshare"
deletion_delay = "2h"
network_config_list = [
  {
    role                   = "client"
    vpc_name               = "client-vpc"
    vpc_cidr_block         = "10.0.0.0/16"
    subnet_names           = ["client-subnet"]
    subnet_cidr_block      = ["10.0.0.0/24"]
    security_group_name    = "client-sg"
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
          from_port  = 2049
          to_port    = 2049
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

vm_config_list = [{
  vm_name                     = "client-vm"
  role                        = "client"
  subnet_name                 = "client-subnet"
  security_group_name         = "client-sg"
  associate_public_ip_address = true
  }
]

loadbalancer_config_list = []

efs_name_prefix = "perfevalefs"