scenario_type  = "perf-eval"
scenario_name  = "lb-cross-region-iperf"
deletion_delay = "2h"
network_config_list = [
  {
    role           = "network"
    vpc_name       = "server-vpc"
    vpc_cidr_block = "172.16.0.0/16"
    subnet = [
      {
        name        = "server-subnet"
        cidr_block  = "172.16.0.0/24"
        zone_suffix = "c"
      }
    ]
    security_group_name = "server-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "client-subnet-rt-assoc"
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
          from_port  = 20000
          to_port    = 20000
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
loadbalancer_config_list = [{
  role               = "ingress"
  vpc_name           = "server-vpc"
  subnet_names       = ["server-subnet"]
  load_balancer_type = "network"
  lb_target_group = [{
    role       = "nlb-tg"
    tg_suffix  = "tcp"
    port       = 20001
    protocol   = "TCP"
    rule_count = 1
    vpc_name   = "server-vpc"
    health_check = {
      port                = "20000"
      protocol            = "TCP"
      interval            = 10
      timeout             = 10
      healthy_threshold   = 2
      unhealthy_threshold = 2
    }
    lb_listener = {
      port     = 20001
      protocol = "TCP"
    }
    lb_target_group_attachment = {
      vm_name = "server-vm"
      port    = 20001
    }
    },
    {
      role       = "nlb-tg"
      tg_suffix  = "udp"
      port       = 20002
      protocol   = "UDP"
      rule_count = 1
      vpc_name   = "server-vpc"
      health_check = {
        port                = "20000"
        protocol            = "TCP"
        interval            = 10
        timeout             = 10
        healthy_threshold   = 2
        unhealthy_threshold = 2
      }
      lb_listener = {
        port     = 20002
        protocol = "UDP"
      }
      lb_target_group_attachment = {
        vm_name = "server-vm"
        port    = 20002
      }
    }
  ]
}]
vm_config_list = [
  {
    vm_name                     = "server-vm"
    role                        = "server"
    subnet_name                 = "server-subnet"
    security_group_name         = "server-sg"
    associate_public_ip_address = true
    zone_suffix                 = "c"
  }
]