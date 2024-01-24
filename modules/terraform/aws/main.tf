locals {
  region                    = lookup(var.json_input, "region", "us-east-1")
  zone                      = lookup(var.json_input, "zone", "us-east-1b")
  machine_type              = lookup(var.json_input, "machine_type", "m5.4xlarge")
  run_id                    = lookup(var.json_input, "run_id", "123456")
  user_data_path            = lookup(var.json_input, "user_data_path", "")
  data_disk_size_gb         = lookup(var.json_input, "data_disk_size_gb", null)
  data_disk_volume_type     = lookup(var.json_input, "data_disk_volume_type", "")
  data_disk_iops_read_write = lookup(var.json_input, "data_disk_iops_read_write", null)
  data_disk_mbps_read_write = lookup(var.json_input, "data_disk_mbps_read_write", null)

  efs_performance_mode                = lookup(var.json_input, "efs_performance_mode", null)
  efs_throughput_mode                 = lookup(var.json_input, "efs_throughput_mode", null)
  efs_provisioned_throughput_in_mibps = lookup(var.json_input, "efs_provisioned_throughput_in_mibps", null)

  tags = {
    "owner"             = lookup(var.json_input, "owner", "github_actions")
    "scenario"          = "${var.scenario_type}-${var.scenario_name}"
    "creation_time"     = timestamp()
    "deletion_due_time" = timeadd(timestamp(), var.deletion_delay)
    "run_id"            = local.run_id
  }

  network_config_map      = { for network in var.network_config_list : network.role => network }
  loadbalancer_config_map = { for loadbalancer in var.loadbalancer_config_list : loadbalancer.role => loadbalancer }
  vm_config_map           = { for vm in var.vm_config_list : vm.vm_name => vm }

  all_lb_arns = { for loadbalancer in var.loadbalancer_config_list : loadbalancer.role => module.load_balancer[loadbalancer.role].lb_arn }
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
  key_name   = "admin-key-pair-${local.run_id}"
  public_key = tls_private_key.admin_ssh_key.public_key_openssh
  tags       = local.tags
}

module "virtual_network" {
  for_each = local.network_config_map

  source         = "./virtual-network"
  network_config = each.value
  region         = local.region
  zone           = local.zone
  tags           = local.tags
}

module "virtual_machine" {
  for_each = local.vm_config_map

  source = "./virtual-machine"
  vm_config = merge(each.value, {
    data_disk_config = (local.data_disk_volume_type == null || local.user_data_path == "") ? null : {
      data_disk_volume_type     = local.data_disk_volume_type
      data_disk_size_gb         = tonumber(local.data_disk_size_gb)
      data_disk_iops_read_write = tonumber(local.data_disk_iops_read_write)
      data_disk_mbps_read_write = tonumber(local.data_disk_mbps_read_write)
    }
  })
  admin_key_pair_name = aws_key_pair.admin_key_pair.key_name
  tags                = local.tags
  run_id              = local.run_id
  machine_type        = local.machine_type
  user_data_path      = local.user_data_path
  depends_on          = [module.virtual_network]
  region              = local.region
  zone                = local.zone
}

module "load_balancer" {
  for_each = local.loadbalancer_config_map

  source              = "./load-balancer"
  loadbalancer_config = each.value
  run_id              = local.run_id
  tags                = local.tags
  depends_on          = [module.virtual_machine, module.virtual_network]
}

module "bucket" {
  source = "./bucket"

  count              = var.bucket_name_prefix != "" ? 1 : 0
  bucket_name_prefix = var.bucket_name_prefix
  run_id             = local.run_id
  tags               = local.tags
}

module "efs" {
  source = "./efs"

  count                           = var.efs_name_prefix != "" ? 1 : 0
  efs_name_prefix                 = var.efs_name_prefix
  run_id                          = local.run_id
  performance_mode                = local.efs_performance_mode
  throughput_mode                 = local.efs_throughput_mode
  provisioned_throughput_in_mibps = local.efs_provisioned_throughput_in_mibps
  tags                            = local.tags
}

module "privatelink" {
  source = "./private-link"

  count                      = var.private_link_conf == null ? 0 : 1
  run_id                     = local.run_id
  client_vpc_name            = var.private_link_conf.client_vpc_name
  client_subnet_name         = var.private_link_conf.client_subnet_name
  client_security_group_name = var.private_link_conf.client_security_group_name
  service_lb_arn             = local.all_lb_arns[var.private_link_conf.service_lb_role]
  tags                       = local.tags

  depends_on = [module.load_balancer]
}