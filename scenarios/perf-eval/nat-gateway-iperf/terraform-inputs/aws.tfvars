scenario_type  = "perf-eval"
scenario_name  = "nat-gateway-iperf"
deletion_delay = "2h"
network_config_list = [
  {
    role           = "network"
    vpc_name       = "same-vpc"
    vpc_cidr_block = "10.2.0.0/16"
    subnet = [
      {
        name        = "client-subnet"
        cidr_block  = "10.2.1.0/24"
        zone_suffix = "a"
      },
      {
        name        = "server-subnet"
        cidr_block  = "10.2.2.0/24"
        zone_suffix = "b"
      },
      {
        name        = "nat-subnet"
        cidr_block  = "10.2.3.0/24"
        zone_suffix = "a"
      }
    ]
    security_group_name = "same-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      },
      {
        name             = "nat-rt"
        cidr_block       = "0.0.0.0/0"
        nat_gateway_name = "nat-gw"
      }
    ],
    route_table_associations = [
      {
        name             = "client-subnet-rt-assoc"
        subnet_name      = "client-subnet"
        route_table_name = "nat-rt"
      },
      {
        name             = "server-subnet-rt-assoc"
        subnet_name      = "server-subnet"
        route_table_name = "internet-rt"
      },
      {
        name             = "nat-subnet-rt-assoc"
        subnet_name      = "nat-subnet"
        route_table_name = "internet-rt"
      }
    ]
    nat_gateways = [{
      name           = "nat-gw"
      public_ip_name = "nat-gw-eip"
      subnet_name    = "nat-subnet"
    }]
    nat_gateway_public_ips = [{
      name = "nat-gw-eip"
    }]
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
  vm_name                     = "jumpbox-vm"
  role                        = "jumpbox"
  subnet_name                 = "nat-subnet"
  security_group_name         = "same-sg"
  associate_public_ip_address = true
  zone_suffix                 = "a"
  },
  {
    vm_name                     = "client-vm"
    role                        = "client"
    subnet_name                 = "client-subnet"
    security_group_name         = "same-sg"
    associate_public_ip_address = false
    zone_suffix                 = "a"
  },
  {
    vm_name                     = "server-vm"
    role                        = "server"
    subnet_name                 = "server-subnet"
    security_group_name         = "same-sg"
    associate_public_ip_address = true
    zone_suffix                 = "b"
  }
]