locals {
  region = lookup(var.json_input, "region", "us-east-1")
  run_id = lookup(var.json_input, "run_id", "123456")

  tags = {
    "owner"             = var.owner
    "scenario"          = "${var.scenario_type}-${var.scenario_name}"
    "creation_time"     = timestamp()
    "deletion_due_time" = timeadd(timestamp(), var.deletion_delay)
    "run_id"            = local.run_id
  }

  network_config_map = { for network in var.network_config_list : network.role => network }
  eks_config_map     = { for eks in var.eks_config_list : eks.eks_name => eks }
  all_vpcs           = { for network in var.network_config_list : network.vpc_name => module.virtual_network[network.role].vpc }
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


module "virtual_network" {
  for_each = local.network_config_map

  source         = "./virtual-network"
  network_config = each.value
  region         = local.region
  tags           = local.tags
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
