locals {
  region         = lookup(var.json_input, "region", "us-east-1")
  az             = lookup(var.json_input, "az", "us-east-1b")
  instance_type  = lookup(var.json_input, "instance_type", "m5.4xlarge")
  job_id         = lookup(var.json_input, "job_id", "123456")
  user_data_path = lookup(var.json_input, "user_data_path", "")

  tags = {
    "owner"             = lookup(var.json_input, "owner", "github_actions")
    "scenario"          = var.scenario_name
    "creation_time"     = timestamp()
    "deletion_due_time" = timeadd(timestamp(), var.deletion_delay)
    "job_id"            = local.job_id
  }

  network_config_map      = { for network in var.network_config_list : network.role => network }
  loadbalancer_config_map = { for loadbalancer in var.loadbalancer_config_list : loadbalancer.role => loadbalancer }
  vm_config_map           = { for vm in var.vm_config_list : vm.vm_name => vm }
}

provider "aws" {
  region = local.region
}

resource "tls_private_key" "admin_ssh_key" {
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "local_file" "ssh_private_key" {
  content  = tls_private_key.admin_ssh_key.private_key_pem
  filename = "private_key.pem"

  provisioner "local-exec" {
    command = "chmod 600 private_key.pem"
  }
}

resource "aws_key_pair" "admin_key_pair" {
  key_name   = "admin-key-pair-${local.job_id}"
  public_key = tls_private_key.admin_ssh_key.public_key_openssh
  tags       = local.tags
}

module "virtual_network" {
  for_each = local.network_config_map

  source         = "./virtual-network"
  network_config = each.value
  az             = local.az
  job_id         = local.job_id
  tags           = local.tags
}

module "virtual_machine" {
  for_each = local.vm_config_map

  source              = "./virtual-machine"
  vm_config           = each.value
  admin_key_pair_name = aws_key_pair.admin_key_pair.key_name
  tags                = local.tags
  job_id              = local.job_id
  instance_type       = local.instance_type
  user_data_path      = local.user_data_path
  depends_on          = [module.virtual_network]
}

module "load_balancer" {
  for_each = local.loadbalancer_config_map

  source              = "./load-balancer"
  loadbalancer_config = each.value
  job_id              = local.job_id
  tags                = local.tags
  depends_on          = [module.virtual_machine, module.virtual_network]
}
