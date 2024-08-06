scenario_type  = "perf-eval"
scenario_name  = "ilb-diff-zone-jmeter"
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
      }
    ]
    security_group_name = "same-sg"
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
      },
      {
        name             = "server-subnet-rt-assoc"
        subnet_name      = "server-subnet"
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
          from_port  = 0
          to_port    = 0
          protocol   = "-1"
          cidr_block = "0.0.0.0/0"
        }
      ]
    }
  },
]
loadbalancer_config_list = [{
  role               = "ingress"
  vpc_name           = "same-vpc"
  subnet_names       = ["server-subnet"]
  load_balancer_type = "network",
  is_internal_lb     = true,
  lb_target_group = [{
    role      = "nlb-tg"
    tg_suffix = "http"
    port      = 80
    protocol  = "TCP"
    vpc_name  = "same-vpc"
    health_check = {
      port                = "80"
      protocol            = "TCP"
      interval            = 15
      timeout             = 10
      healthy_threshold   = 3
      unhealthy_threshold = 3
    }
    lb_listener = [{
      port     = 80
      protocol = "TCP"
    }]
    lb_target_group_attachment = [{
      vm_name = "server-vm"
      port    = 80
    }]
    },
    {
      role      = "nlb-tg"
      tg_suffix = "https"
      port      = 443
      protocol  = "TCP"
      vpc_name  = "same-vpc"
      health_check = {
        port                = "443"
        protocol            = "TCP"
        interval            = 15
        timeout             = 10
        healthy_threshold   = 3
        unhealthy_threshold = 3
      }
      lb_listener = [{
        port     = 443
        protocol = "TCP"
      }]
      lb_target_group_attachment = [{
        vm_name = "server-vm"
        port    = 443
      }]
    }
  ]
}]
vm_config_list = [{
  vm_name                     = "client-vm"
  role                        = "client"
  subnet_name                 = "client-subnet"
  security_group_name         = "same-sg"
  associate_public_ip_address = true
  zone_suffix                 = "a"
  ami_config = {
    most_recent         = true
    name                = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
    virtualization_type = "hvm"
    architecture        = "x86_64"
    owners              = ["099720109477"]
  }
  },
  {
    vm_name                     = "server-vm"
    role                        = "server"
    subnet_name                 = "server-subnet"
    security_group_name         = "same-sg"
    associate_public_ip_address = true
    zone_suffix                 = "b"
    ami_config = {
      most_recent         = true
      name                = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
      virtualization_type = "hvm"
      architecture        = "x86_64"
      owners              = ["099720109477"]
    }
  }
]
