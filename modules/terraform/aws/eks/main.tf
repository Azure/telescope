locals {
  role               = var.eks_config.role
  eks_cluster_name   = "${var.eks_config.eks_name}-${var.run_id}"
  eks_node_group_map = { for node_group in var.eks_config.eks_managed_node_groups : node_group.name => node_group }
  karpenter_addons_map = {
    for addon in [{ name = "vpc-cni", policy_arns = ["AmazonEKS_CNI_Policy"] }, { name = "kube-proxy" }, { name = "coredns" }] : addon.name =>
    {
      name            = addon.name
      version         = lookup(addon, "version", null)
      service_account = lookup(addon, "service_account", null)
      policy_arns     = lookup(addon, "policy_arns", [])
    }
  }

  eks_addons_map         = { for addon in var.eks_config.eks_addons : addon.name => addon }
  updated_eks_addons_map = var.eks_config.enable_karpenter ? merge(local.karpenter_addons_map, local.eks_addons_map) : local.eks_addons_map
  policy_arns            = var.eks_config.policy_arns
}

data "aws_subnets" "subnets" {
  filter {
    name   = "tag:run_id"
    values = [var.run_id]
  }

  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com", "ec2.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "eks_cluster_role" {
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy_attachment" "policy_attachments" {
  for_each = toset(local.policy_arns)

  policy_arn = "arn:aws:iam::aws:policy/${each.value}"
  role       = aws_iam_role.eks_cluster_role.name
}

# Create EKS Cluster
resource "aws_eks_cluster" "eks" {
  name     = local.eks_cluster_name
  role_arn = aws_iam_role.eks_cluster_role.arn

  vpc_config {
    subnet_ids = toset(data.aws_subnets.subnets.ids)
  }

  access_config {
    authentication_mode                         = "API_AND_CONFIG_MAP"
    bootstrap_cluster_creator_admin_permissions = true
  }

  version = var.eks_config.kubernetes_version

  depends_on = [
    aws_iam_role_policy_attachment.policy_attachments
  ]

  tags = {
    "role" = local.role
  }
}

resource "aws_eks_node_group" "eks_managed_node_groups" {

  for_each = local.eks_node_group_map

  node_group_name = each.value.name
  cluster_name    = aws_eks_cluster.eks.name
  node_role_arn   = aws_iam_role.eks_cluster_role.arn
  subnet_ids      = toset(data.aws_subnets.subnets.ids)

  scaling_config {
    min_size     = each.value.min_size
    max_size     = each.value.max_size
    desired_size = each.value.desired_size
  }

  dynamic "taint" {
    for_each = each.value.taints
    content {
      key    = taint.value["key"]
      value  = taint.value["value"]
      effect = taint.value["effect"]
    }
  }

  ami_type       = each.value.ami_type
  instance_types = each.value.instance_types
  capacity_type  = each.value.capacity_type
  labels         = each.value.labels

  tags = {
    "Name" = each.value.name
  }
  depends_on = [
    aws_eks_cluster.eks,
    aws_iam_role_policy_attachment.policy_attachments
  ]
}

module "eks_addon" {
  source = "./addon"

  count = length(local.updated_eks_addons_map) != 0 ? 1 : 0

  eks_addon_config_map      = local.updated_eks_addons_map
  cluster_name              = aws_eks_cluster.eks.name
  cluster_oidc_provider_url = aws_eks_cluster.eks.identity[0].oidc[0].issuer
  depends_on                = [aws_eks_node_group.eks_managed_node_groups]
}

module "karpenter" {
  count = var.eks_config.enable_karpenter ? 1 : 0

  source = "./karpenter"

  cluster_name          = aws_eks_cluster.eks.name
  region                = var.region
  tags                  = var.tags
  cluster_iam_role_name = aws_iam_role.eks_cluster_role.name

  depends_on = [aws_eks_node_group.eks_managed_node_groups]
}
