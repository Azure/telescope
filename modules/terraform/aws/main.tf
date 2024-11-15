locals {
  region        = lookup(var.json_input, "region", "us-east-1")
  run_id        = lookup(var.json_input, "run_id", "123456")
  creation_time = var.json_input["creation_time"]

  non_computed_tags = {
    # Note: Define only non computed values (i.e. values that do not change for each resource). This is required due to a limitation at "aws" provider default_tags.
    "owner"             = var.owner # note: MUST NOT REMOVE (it's used for resources accountability and cost tracking)
    "scenario"          = "${var.scenario_type}-${var.scenario_name}"
    "creation_time"     = local.creation_time                              # note: should not use timestamp() since it is a computed value
    "deletion_due_time" = timeadd(local.creation_time, var.deletion_delay) # note: MUST NOT BE REMOVED (it's used by the garbage collector)
    "run_id"            = local.run_id
  }

  tags = merge(local.non_computed_tags, {
    # Addicional computed tags
  })

  network_config_map = { for network in var.network_config_list : network.role => network }
  eks_config_map     = { for eks in var.eks_config_list : eks.eks_name => eks }
  all_vpcs           = { for network in var.network_config_list : network.vpc_name => module.virtual_network[network.role].vpc }
}

provider "aws" {
  region = local.region
  default_tags {
    # Note: Aws provider's default_tags does not support computed values (e.g. timestamp()) (see: https://github.com/hashicorp/terraform-provider-aws/issues/19583#issuecomment-1561337902)
    tags = local.non_computed_tags
  }
}

module "virtual_network" {
  for_each = local.network_config_map

  source         = "./virtual-network"
  network_config = each.value
  region         = local.region
}

module "eks" {
  for_each = local.eks_config_map

  source     = "./eks"
  run_id     = local.run_id
  region     = local.region
  vpc_id     = local.all_vpcs[each.value.vpc_name].id
  eks_config = each.value
  tags       = local.tags
  depends_on = [module.virtual_network]
}


variable "eks" {
  type    = object({})
  default = {}
}

output "eks" {
  value = module.eks
} 