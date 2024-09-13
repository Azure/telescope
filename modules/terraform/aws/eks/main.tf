locals {
  role               = var.eks_config.role
  eks_node_group_map = { for node_group in var.eks_config.eks_managed_node_groups : node_group.name => node_group }
  eks_addons_map     = { for addon in var.eks_config.eks_addons : addon.name => addon }
  policy_arns        = var.eks_config.policy_arns
  eks_cluster_name   = "${var.eks_config.eks_name}-${var.run_id}"
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
  tags               = var.tags
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

  depends_on = [
    aws_iam_role_policy_attachment.policy_attachments
  ]

  tags = merge(
    var.tags,
    {
      "role" = local.role
    }
  )
}

resource "aws_cloudformation_stack" "cluster_stack" {
  name = "${local.eks_cluster_name}-stack"

  parameters = {
    ClusterName    = local.eks_cluster_name
    ClusterRoleArn = aws_iam_role.eks_cluster_role.arn
  }
  template_body = file("${var.scripts_dir}/cloudformation.yaml")
  capabilities  = ["CAPABILITY_NAMED_IAM"]
}

resource "terraform_data" "install_karpenter" {
  provisioner "local-exec" {
    command = "${var.scripts_dir}/install-karpenter.sh"
    environment = {
      EKS_CLUSTER_NAME = local.eks_cluster_name
    }
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
			#!/bin/bash
			set -e
			helm uninstall karpenter --namespace kube-system
			EOT
  }
  depends_on = [aws_eks_cluster.eks]
}



data "aws_iam_role" "role" {
  name = "${var.eks_config.pod_associations.role_arn_name}-${aws_eks_cluster.eks.name}"
}

resource "aws_eks_pod_identity_association" "association" {
  cluster_name    = aws_eks_cluster.eks.name
  namespace       = var.eks_config.pod_associations.namespace
  service_account = var.eks_config.pod_associations.service_account_name
  role_arn        = data.aws_iam_role.role.arn
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

  tags = merge(var.tags, {
    "Name" = each.value.name
  })
  depends_on = [
    aws_eks_cluster.eks,
    aws_iam_role_policy_attachment.policy_attachments
  ]

}


module "eks_addon" {
  source = "./addon"

  count = length(var.eks_config.eks_addons) != 0 ? 1 : 0

  eks_addon_config_map      = local.eks_addons_map
  cluster_name              = aws_eks_cluster.eks.name
  cluster_oidc_provider_url = aws_eks_cluster.eks.identity[0].oidc[0].issuer
  tags                      = var.tags
  depends_on                = [aws_eks_cluster.eks, aws_eks_node_group.eks_managed_node_groups]
}
