locals {
  role               = var.eks_config.role
  eks_node_group_map = { for node_group in var.eks_config.eks_managed_node_groups : node_group.name => node_group }
  eks_addons_map     = { for addon in var.eks_config.eks_addons : addon.name => addon }
  policy_arns        = var.eks_config.policy_arns
  eks_cluster_name   = var.eks_config.override_cluster_name ? var.eks_config.eks_name : "${var.eks_config.eks_name}-${var.run_id}"
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
    aws_iam_role_policy_attachment.policy_attachments, aws_cloudformation_stack.cluster_stack
  ]

  tags = merge(
    var.tags,
    {
      "role" = local.role
    }
  )
}

resource "aws_cloudformation_stack" "cluster_stack" {
  count = var.eks_config.cloudformation_template_file_name != null ? 1 : 0
  name  = "${local.eks_cluster_name}-stack"

  parameters = {
    ClusterName    = local.eks_cluster_name
    ClusterRoleArn = aws_iam_role.eks_cluster_role.arn
  }
  template_body = file("${var.user_data_path}/${var.eks_config.cloudformation_template_file_name}.yaml")
  capabilities  = ["CAPABILITY_NAMED_IAM"]

  depends_on = [aws_iam_role.eks_cluster_role]
}

resource "terraform_data" "install_karpenter" {
  count = var.eks_config.install_karpenter ? 1 : 0
  provisioner "local-exec" {
    command = <<EOT
			#!/bin/bash
			set -e
			"${var.user_data_path}/install-karpenter.sh"
			sleep 30
			envsubst  < "${var.user_data_path}/NodeClass.yml" | kubectl apply -f -
			
			EOT
    environment = {
      EKS_CLUSTER_NAME  = local.eks_cluster_name
      CLUSTER_ROLE_NAME = aws_iam_role.eks_cluster_role.name
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
  depends_on = [aws_cloudformation_stack.cluster_stack, aws_eks_node_group.eks_managed_node_groups]

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


# data "aws_iam_role" "role" {
#   name       = var.eks_config.pod_associations.role_arn_name
#   depends_on = [aws_cloudformation_stack.cluster_stack]
# }

# resource "aws_eks_pod_identity_association" "association" {
#   count           = 0
#   cluster_name    = aws_eks_cluster.eks.name
#   namespace       = var.eks_config.pod_associations.namespace
#   service_account = var.eks_config.pod_associations.service_account_name
#   role_arn        = data.aws_iam_role.role.arn
#   depends_on      = [module.eks_addon]
# }
