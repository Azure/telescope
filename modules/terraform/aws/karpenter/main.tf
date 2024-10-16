## THIS TO AUTHENTICATE TO ECR, DON'T CHANGE IT
## IF DEFAULT REGION IS ``, NO NEED TO SET ALIAS FOR THIS
## IT IS ONLY USED FOR KARPENTER INSTALLATION
terraform {
  required_version = ">= 1.0.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.32"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.15"
    }
    kubectl = {
      source  = "alekc/kubectl"
      version = ">= 2.0.4"
    }
  }
}
provider "aws" {
  region = "us-east-1"
  alias  = "virginia"
}

provider "aws" {
  region = local.region
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}

provider "kubectl" {
  apply_retry_count      = 10
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  load_config_file       = false
  token                  = data.aws_eks_cluster_auth.this.token
}


locals {
  region                  = lookup(var.json_input, "region", "us-east-1")
  run_id                  = lookup(var.json_input, "run_id", "123456")
  cluster_name            = substr("${var.karpenter_config.cluster_name}-${local.run_id}", 0, 25)
  eks_cluster_version     = var.karpenter_config.eks_cluster_version
  vpc_cidr                = var.karpenter_config.vpc_cidr
  eks_managed_node_group  = var.karpenter_config.eks_managed_node_group
  karpenter_chart_version = var.karpenter_config.karpenter_chart_version

  azs = slice(data.aws_availability_zones.available.names, 0, 3)
}

data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

data "aws_eks_cluster_auth" "this" {
  name = module.eks.cluster_name
}

data "aws_ecrpublic_authorization_token" "token" {
  provider = aws.virginia
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.13.0"

  name = local.cluster_name
  cidr = local.vpc_cidr

  azs             = local.azs
  public_subnets  = [for k, v in local.azs : cidrsubnet(local.vpc_cidr, 8, k)]
  private_subnets = ["10.0.32.0/19", "10.0.64.0/19", "10.0.96.0/19"]

  create_igw              = true
  enable_nat_gateway      = true
  single_nat_gateway      = true
  enable_dns_hostnames    = true
  enable_dns_support      = true
  map_public_ip_on_launch = true

  # Manage so we can name
  manage_default_network_acl    = true
  default_network_acl_tags      = { Name = "${local.cluster_name}-default" }
  manage_default_route_table    = true
  default_route_table_tags      = { Name = "${local.cluster_name}-default" }
  manage_default_security_group = true
  default_security_group_tags   = { Name = "${local.cluster_name}-default" }

  public_subnet_tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
  }

  private_subnet_tags = {
    "kubernetes.io/cluster/${local.cluster_name}" = "shared"
    "karpenter.sh/discovery"                      = local.cluster_name
  }

}

###############################################################################
# EKS Cluster
###############################################################################
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "20.24.0"

  cluster_name                   = local.cluster_name
  cluster_version                = local.eks_cluster_version
  cluster_endpoint_public_access = true

  cluster_addons = {
    kube-proxy = { most_recent = true }
    coredns    = { most_recent = true }

    vpc-cni = {
      most_recent    = true
      before_compute = true
      configuration_values = jsonencode({
        env = {
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"
        }
      })
    }
  }

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  create_cloudwatch_log_group              = false
  create_cluster_security_group            = false
  create_node_security_group               = false
  authentication_mode                      = "API_AND_CONFIG_MAP"
  enable_cluster_creator_admin_permissions = true

  eks_managed_node_groups = {
    managed_nodes = {
      node_group_name       = local.eks_managed_node_group.name
      instance_types        = local.eks_managed_node_group.instance_types
      capacity_type         = local.eks_managed_node_group.capacity_type
      create_security_group = false

      subnet_ids   = module.vpc.private_subnets
      max_size     = local.eks_managed_node_group.max_size
      desired_size = local.eks_managed_node_group.desired_size
      min_size     = local.eks_managed_node_group.min_size

      # Launch template configuration
      create_launch_template = true # false will use the default launch template

      labels = {
        intent = "control-apps"
      }
    }
  }

  tags = {
    "karpenter.sh/discovery" = local.cluster_name
  }

  depends_on = [
    module.vpc.vpc_id
  ]
}

module "eks_blueprints_addons" {
  source  = "aws-ia/eks-blueprints-addons/aws"
  version = "1.16.3"

  cluster_name      = module.eks.cluster_name
  cluster_endpoint  = module.eks.cluster_endpoint
  cluster_version   = module.eks.cluster_version
  oidc_provider_arn = module.eks.oidc_provider_arn

  create_delay_dependencies = [for prof in module.eks.eks_managed_node_groups : prof.node_group_arn]

  enable_aws_load_balancer_controller = false
  enable_metrics_server               = false
  eks_addons = {
  }

  # Enable Karpenter for node autoscaling
  enable_karpenter = true
  karpenter = {
    chart_version       = local.karpenter_chart_version
    repository_username = data.aws_ecrpublic_authorization_token.token.user_name
    repository_password = data.aws_ecrpublic_authorization_token.token.password
    timeout             = 600
  }
  karpenter_enable_spot_termination          = true
  karpenter_enable_instance_profile_creation = true
  karpenter_node = {
    iam_role_use_name_prefix = false
  }

  tags = local.tags

  depends_on = [
    module.eks.cluster_id
  ]
}

module "aws-auth" {
  source  = "terraform-aws-modules/eks/aws//modules/aws-auth"
  version = ">= 20.24"

  manage_aws_auth_configmap = true

  aws_auth_roles = [
    {
      rolearn  = module.eks_blueprints_addons.karpenter.node_iam_role_arn
      username = "system:node:{{EC2PrivateDNSName}}"
      groups   = ["system:bootstrappers", "system:nodes"]
    },
  ]

  depends_on = [
    module.eks.cluster_id
  ]
}

##############################################################################################
# Karpenter settings
# https://github.com/aws-samples/karpenter-blueprints/blob/main/cluster/terraform/karpenter.tf
##############################################################################################
resource "kubectl_manifest" "karpenter_default_ec2_node_class" {
  yaml_body = templatefile("${path.module}/karpenter_default_ec2_node_class.tftpl", {
    node_iam_role_name = module.eks_blueprints_addons.karpenter.node_iam_role_name
    cluster_name       = local.cluster_name
  })

  depends_on = [
    module.eks.cluster_id,
    module.eks_blueprints_addons.karpenter,
  ]
}
