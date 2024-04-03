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
  eks_config_map          = { for eks in var.eks_config_list : eks.eks_name => eks }

  all_lb_arns = { for loadbalancer in var.loadbalancer_config_list : loadbalancer.role => module.load_balancer[loadbalancer.role].lb_arn }
  all_vpcs    = { for network in var.network_config_list : network.vpc_name => module.virtual_network[network.role].vpc }
  all_route_tables = { for network in var.network_config_list : network.route_tables.route_table_name => module.virtual_machine[network].route_table }
}

terraform {
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

module "privateendpoint" {
  source = "./vpc-endpoint"

  count = var.pe_config == null ? 0 : 1

  vpc_id = local.all_vpcs[var.pe_config.vpc_name].id
  route_table_ids = [local.all_route_tables[var.pe_config.route_table_name].id]

  tags = local.tags
  
  pe_config = var.pe_config
}