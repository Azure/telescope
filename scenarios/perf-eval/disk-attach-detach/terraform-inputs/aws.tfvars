scenario_type  = "perf-eval"
scenario_name  = "disk-attach-dettach"
deletion_delay = "2h"
network_config_list = [
  {
    role           = "disk-attach-detach-net-role"
    vpc_name       = "disk-attach-detach-vpc"
    vpc_cidr_block = "10.0.0.0/16"
    subnet = [{
      name        = "disk-attach-detach-subnet"
      cidr_block  = "10.0.0.0/24"
      zone_suffix = "a"
    }]
    security_group_name      = "disk-attach-detach-nsg"
    route_tables             = [],
    route_table_associations = []
    sg_rules = {
      ingress = []
      egress  = []
    }
  }
]

vm_config_list = [{
  info_column_name            = "cloud_info.vm_info"
  vm_name                     = "single-attach-detach-vm"
  role                        = "disk-attach-detach-target-vm-role"
  subnet_name                 = "disk-attach-detach-subnet"
  security_group_name         = "disk-attach-detach-nsg"
  associate_public_ip_address = true
  zone_suffix                 = "a"
}]

data_disk_config = {
  zone_suffix = "a"
}

loadbalancer_config_list = []
