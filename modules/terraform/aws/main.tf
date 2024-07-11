locals {
  region                    = lookup(var.json_input, "region", "us-east-1")
  machine_type              = lookup(var.json_input, "machine_type", "m5.4xlarge")
  run_id                    = lookup(var.json_input, "run_id", "123456")
  public_key_path           = lookup(var.json_input, "public_key_path", "")
  user_data_path            = lookup(var.json_input, "user_data_path", "")
  data_disk_size_gb         = lookup(var.json_input, "data_disk_size_gb", null)
  data_disk_volume_type     = lookup(var.json_input, "data_disk_volume_type", "")
  data_disk_iops_read_write = lookup(var.json_input, "data_disk_iops_read_write", null)
  data_disk_mbps_read_write = lookup(var.json_input, "data_disk_mbps_read_write", null)
  data_disk_count           = lookup(var.json_input, "data_disk_count", 1)
  vm_count_override         = lookup(var.json_input, "vm_count_override", null)

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
  expanded_vm_config_list = flatten([
  for vm in var.vm_config_list : [
    for i in range(local.vm_count_override > 0 ? local.vm_count_override : vm.count) : {
      vm_name                     = vm.count > 1 ? "${vm.vm_name}-${i+1}" : vm.vm_name
      zone_suffix                 = vm.zone_suffix
      role                        = vm.role
      subnet_name                 = vm.subnet_name
      security_group_name         = vm.security_group_name
      associate_public_ip_address = vm.associate_public_ip_address
      info_column_name            = vm.info_column_name
      ami_config                  = vm.ami_config
    }]
  ])
  vm_config_map           = { for vm in local.expanded_vm_config_list : vm.vm_name => vm }
  eks_config_map          = { for eks in var.eks_config_list : eks.eks_name => eks }

  all_lb_arns          = { for loadbalancer in var.loadbalancer_config_list : loadbalancer.role => module.load_balancer[loadbalancer.role].lb_arn }
  all_vpcs             = { for network in var.network_config_list : network.vpc_name => module.virtual_network[network.role].vpc }
  all_vms              = { for vm in local.expanded_vm_config_list : vm.vm_name => module.virtual_machine[vm.vm_name].vm }
  all_devices_suffixes = ["f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p"]
}

terraform {
  required_version = ">=1.5.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "<= 5.38"
    }
  }
}

provider "aws" {
  region = local.region
}

resource "aws_key_pair" "admin_key_pair" {
  key_name   = "admin-key-pair-${local.run_id}-${terraform.workspace}"
  public_key = file(local.public_key_path)
  tags       = local.tags
}

module "virtual_network" {
  for_each = local.network_config_map

  source         = "./virtual-network"
  network_config = each.value
  region         = local.region
  tags           = local.tags
}

module "virtual_machine" {
  for_each = local.vm_config_map

  source              = "./virtual-machine"
  vm_config           = each.value
  admin_key_pair_name = aws_key_pair.admin_key_pair.key_name
  tags                = local.tags
  run_id              = local.run_id
  machine_type        = local.machine_type
  user_data_path      = local.user_data_path
  depends_on          = [module.virtual_network]
  region              = local.region
}

module "data_disk" {
  count = var.data_disk_config == null ? 0 : local.data_disk_count

  source                    = "./data-disk"
  zone                      = "${local.region}${var.data_disk_config.zone_suffix}"
  tags                      = local.tags
  data_disk_volume_type     = local.data_disk_volume_type
  data_disk_size_gb         = tonumber(local.data_disk_size_gb)
  data_disk_iops_read_write = tonumber(local.data_disk_iops_read_write)
  data_disk_mbps_read_write = tonumber(local.data_disk_mbps_read_write)
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

  object_config = var.bucket_object_config == null ? null : {
    source_path = "${local.user_data_path}/${var.bucket_object_config.bucket_source_file_name}"
    file_key    = var.bucket_object_config.bucket_file_key
  }
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

module "eks" {
  for_each = local.eks_config_map

  source     = "./eks"
  run_id     = local.run_id
  vpc_id     = local.all_vpcs[each.value.vpc_name].id
  eks_config = each.value
  tags       = local.tags
  depends_on = [module.virtual_network]
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

resource "aws_volume_attachment" "attach" {
  count = try(var.data_disk_config.vm_name, null) != null ? local.data_disk_count : 0

  device_name = "/dev/sd${element(local.all_devices_suffixes, count.index)}"
  volume_id   = module.data_disk[count.index].data_disk.id
  instance_id = local.all_vms[var.data_disk_config.vm_name].id
}

module "privateendpoint" {
  source = "./vpc-endpoint"

  count     = var.pe_config == null ? 0 : 1
  pe_config = var.pe_config

  vpc_id = local.all_vpcs[var.pe_config.pe_vpc_name].id

  tags = local.tags
}
