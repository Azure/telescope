scenario_name  = "perf_eval_lb_https_aws"
deletion_delay = "2h"
network_config_list = [
  {
    name_prefix            = "server"
    vpc_name               = "server-vpc"
    vpc_cidr_block         = "10.1.0.0/16"
    subnet_names           = ["server-subnet"]
    subnet_cidr_block      = ["10.1.1.0/24"]
    security_group_name    = "server-sg"
    route_table_cidr_block = "0.0.0.0/0"
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
          from_port  = 0
          to_port    = 0
          protocol   = "-1"
          cidr_block = "0.0.0.0/0"
        }
      ]
    }
  },
  {
    name_prefix            = "client"
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
loadbalancer_config_list = [{
  name_prefix        = "nlb"
  vpc_name           = "server-vpc"
  subnet_name        = "server-subnet"
  load_balancer_type = "network"
  lb_target_group = [{
    name_prefix = "nlb-tg"
    tg_suffix = "http"
    port        = 80
    protocol    = "TCP"
    rule_count  = 1
    vpc_name    = "server-vpc"
    health_check = {
      port                = "80"
      protocol            = "TCP"
      interval            = 15
      timeout             = 10
      healthy_threshold   = 3
      unhealthy_threshold = 3
    }
    lb_listener = {
      port     = 80
      protocol = "TCP"
    }
    lb_target_group_attachment = {
      vm_name = "server-vm"
      port    = 80
    }
    },
    {
      name_prefix = "nlb-tg"
      tg_suffix = "https"
      port        = 443
      protocol    = "TCP"
      rule_count  = 1
      vpc_name    = "server-vpc"
      health_check = {
        port                = "443"
        protocol            = "TCP"
        interval            = 15
        timeout             = 10
        healthy_threshold   = 3
        unhealthy_threshold = 3
      }
      lb_listener = {
        port     = 443
        protocol = "TCP"
      }
      lb_target_group_attachment = {
        vm_name = "server-vm"
        port    = 443
      }
    }
  ]
}]

vm_config_list = [{
  vm_name                     = "client-vm"
  name_prefix                 = "client"
  subnet_name                 = "client-subnet"
  security_group_name         = "client-sg"
  associate_public_ip_address = true
  },
  {
    vm_name                     = "server-vm"
    name_prefix                 = "server"
    subnet_name                 = "server-subnet"
    security_group_name         = "server-sg"
    associate_public_ip_address = true
  }
]