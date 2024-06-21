scenario_type  = "perf-eval"
scenario_name  = "vm-redeploy"
deletion_delay = "2h"
network_config_list = [
  {
    role           = "vm-redeploy-net-role"
    vpc_name       = "vm-redeploy-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [{
      name        = "vm-redeploy-subnet"
      cidr_block  = "10.0.0.0/24"
      zone_suffix = "a"
    }]
    security_group_name = "vm-redeploy-nsg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "vm-redeploy-subnet-rt-assoc"
        subnet_name      = "vm-redeploy-subnet"
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
        },
        {
          from_port  = -1
          to_port    = -1
          protocol   = "icmp"
          cidr_block = "0.0.0.0/0"
        },
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

vm_config_list = [
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-1"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-2"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-3"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-4"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-5"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-6"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-7"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-8"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-9"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  },
  {
    info_column_name            = "cloud_info.vm_info"
    vm_name                     = "vm-redeploy-vm-10"
    role                        = "vm-redeploy-role"
    subnet_name                 = "vm-redeploy-subnet"
    security_group_name         = "vm-redeploy-nsg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  }
]
loadbalancer_config_list = []
