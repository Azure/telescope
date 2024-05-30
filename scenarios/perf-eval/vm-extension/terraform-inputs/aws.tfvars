scenario_type  = "perf-eval"
scenario_name  = "vm-extension"
deletion_delay = "2h"

network_config_list = [
  {
    role           = "network"
    vpc_name       = "vm-extension-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [{
      name        = "vm-extension-subnet"
      cidr_block  = "10.0.0.0/24"
      zone_suffix = "a"
    }]
    security_group_name = "vm-extension-nsg"
    route_tables = [
      {
        name       = "vm-extension-subnet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "vm-extension-subnet-rt-assoc"
        subnet_name      = "vm-extension-subnet"
        route_table_name = "vm-extension-subnet-rt"
      }
    ]
    sg_rules = {
      ingress = [
        {
          from_port  = 80
          to_port    = 80
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 443
          to_port    = 443
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        }
      ]
      egress = [
        {
          from_port  = 80
          to_port    = 80
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 443
          to_port    = 443
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        }
      ]
    }
  }
]

vm_config_list = [{
  vm_name                     = "vm-extension-1"
  role                        = "vm-role"
  subnet_name                 = "vm-extension-subnet"
  security_group_name         = "vm-extension-nsg"
  associate_public_ip_address = true
  zone_suffix                 = "a"
  },
  {
    vm_name                     = "vm-extension-2"
    role                        = "vm-role"
    subnet_name                 = "vm-extension-subnet"
    security_group_name         = "vm-extension-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    vm_name                     = "vm-extension-3"
    role                        = "vm-role"
    subnet_name                 = "vm-extension-subnet"
    security_group_name         = "vm-extension-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    vm_name                     = "vm-extension-4"
    role                        = "vm-role"
    subnet_name                 = "vm-extension-subnet"
    security_group_name         = "vm-extension-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    vm_name                     = "vm-extension-5"
    role                        = "vm-role"
    subnet_name                 = "vm-extension-subnet"
    security_group_name         = "vm-extension-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    vm_name                     = "vm-extension-6"
    role                        = "vm-role"
    subnet_name                 = "vm-extension-subnet"
    security_group_name         = "vm-extension-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    vm_name                     = "vm-extension-7"
    role                        = "vm-role"
    subnet_name                 = "vm-extension-subnet"
    security_group_name         = "vm-extension-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    vm_name                     = "vm-extension-8"
    role                        = "vm-role"
    subnet_name                 = "vm-extension-subnet"
    security_group_name         = "vm-extension-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    vm_name                     = "vm-extension-9"
    role                        = "vm-role"
    subnet_name                 = "vm-extension-subnet"
    security_group_name         = "vm-extension-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    vm_name                     = "vm-extension-10"
    role                        = "vm-role"
    subnet_name                 = "vm-extension-subnet"
    security_group_name         = "vm-extension-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
}]