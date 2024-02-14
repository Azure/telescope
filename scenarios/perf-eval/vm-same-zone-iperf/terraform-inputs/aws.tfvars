scenario_type  = "perf-eval"
scenario_name  = "vm-same-zone-iperf"
deletion_delay = "2h"
network_config_list = [
  {
    role           = "network"
    vpc_name       = "same-vpc"
    vpc_cidr_block = "10.2.0.0/16"
    subnet = [{
      name        = "same-subnet"
      cidr_block  = "10.2.1.0/24"
      zone_suffix = "a"
    }]
    security_group_name    = "same-sg"
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
<<<<<<< Updated upstream:scenarios/perf-eval/vm-same-zone-iperf/terraform-inputs/aws.tfvars
loadbalancer_config_list = []
=======
loadbalancer_config_list = [{
  role               = "ingress"
  vpc_name           = "server-vpc"
  subnet_name        = "server-subnet"
  load_balancer_type = "network",
  is_internal_lb     = true,
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

>>>>>>> Stashed changes:scenarios/perf-eval/ilb-iperf/terraform-inputs/aws.tfvars
vm_config_list = [{
  vm_name                     = "client-vm"
  role                        = "client"
  network_role                = "client"
  subnet_name                 = "client-subnet"
  security_group_name         = "client-sg"
  associate_public_ip_address = true
  zone_suffix                 = "a"
  },
  {
    vm_name                     = "server-vm"
    role                        = "server"
    subnet_name                 = "server-subnet"
    security_group_name         = "server-sg"
    associate_public_ip_address = true
    zone_suffix                 = "a"
  }
]
