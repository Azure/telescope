scenario_type  = "perf-eval"
scenario_name  = "vm-cross-region-jmeter"
deletion_delay = "2h"
network_config_list = [
  {
    role           = "client"
    vpc_name       = "client-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [{
      name        = "client-subnet"
      cidr_block  = "10.0.0.0/24"
      zone_suffix = "a"
    }]
    security_group_name = "client-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "client-subnet-rt-assoc"
        subnet_name      = "client-subnet"
        route_table_name = "internet-rt"
      }
    ]
    sg_rules = {
      ingress = [
        {
          from_port  = 2222
          to_port    = 2222
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
loadbalancer_config_list = []

vm_config_list = [{
  vm_name                     = "client-vm"
  role                        = "client"
  network_role                = "client"
  subnet_name                 = "client-subnet"
  security_group_name         = "client-sg"
  associate_public_ip_address = true
  zone_suffix                 = "a"
  }
]