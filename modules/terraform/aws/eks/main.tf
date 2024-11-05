locals {
  role               = var.eks_config.role
  eks_cluster_name   = "${var.eks_config.eks_name}-${var.run_id}"
  eks_node_group_map = { for node_group in var.eks_config.eks_managed_node_groups : node_group.name => node_group }

  eks_config_addons_map = { for addon in var.eks_config.eks_addons : addon.name => addon }

  karpenter_addons_map = {
    for addon in [
      { name = "vpc-cni" },
      { name = "kube-proxy" },
      { name = "coredns" }
    ] : addon.name => addon
    if var.eks_config.enable_karpenter
  }

  # Set default VPC-CNI settings if addon is present in the config
  vpc_cni_addon_map = contains(keys(local.karpenter_addons_map), "vpc-cni") || contains(keys(local.eks_config_addons_map), "vpc-cni") ? {
    "vpc-cni" = {
      name        = "vpc-cni",
      policy_arns = ["AmazonEKS_CNI_Policy"],
      configuration_values = {
        env = {
          # Enable IPv4 prefix delegation to increase the number of available IP addresses on the provisioned EC2 nodes.
          # This significantly increases number of pods that can be run per node. (see: https://aws.amazon.com/blogs/containers/amazon-vpc-cni-increases-pods-per-node-limits/)
          # Note: we've seen that it also prevents ENIs leak caused the issue: https://github.com/aws/amazon-vpc-cni-k8s/issues/608
          ENABLE_PREFIX_DELEGATION = "true"
          WARM_PREFIX_TARGET       = "1"

          ADDITIONAL_ENI_TAGS = jsonencode(var.tags)
        }
      }
    }
  } : {}

  eks_addons_map = merge(local.karpenter_addons_map, local.eks_config_addons_map, local.vpc_cni_addon_map) # note: the order matters (the later takes precedence)

  policy_arns = var.eks_config.policy_arns
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

data "aws_iam_policy_document" "cw_put_metrics" {
  count = var.eks_config.enable_cni_metrics_helper ? 1 : 0

  statement {
    sid = "VisualEditor0"

    actions = ["cloudwatch:PutMetricData"]

    resources = ["*"]
  }
}

resource "aws_iam_policy" "cw_policy" {
  count = var.eks_config.enable_cni_metrics_helper ? 1 : 0

  name        = "cw-policy-${local.eks_cluster_name}"
  description = "Grants permission to write metrics to CloudWatch"
  policy      = data.aws_iam_policy_document.cw_put_metrics[0].json
}

resource "aws_iam_role" "eks_cluster_role" {
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy_attachment" "policy_attachments" {
  for_each = toset(local.policy_arns)

  policy_arn = "arn:aws:iam::aws:policy/${each.value}"
  role       = aws_iam_role.eks_cluster_role.name
}

resource "aws_iam_role_policy_attachment" "cw_policy_attachment" {
  count = var.eks_config.enable_cni_metrics_helper ? 1 : 0

  policy_arn = aws_iam_policy.cw_policy[0].arn
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

# Create OIDC Provider
data "tls_certificate" "eks" {
  url = aws_eks_cluster.eks.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "oidc_provider" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.eks.identity[0].oidc[0].issuer
  tags            = var.tags
  depends_on      = [data.tls_certificate.eks]
}

resource "aws_ec2_tag" "cluster_security_group" {
  for_each    = var.tags
  resource_id = aws_eks_cluster.eks.vpc_config[0].cluster_security_group_id
  key         = each.key
  value       = each.value
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

  count = length(local.eks_addons_map) != 0 ? 1 : 0

  eks_addon_config_map      = local.eks_addons_map
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

module "cluster_autoscaler" {
  count = var.eks_config.enable_cluster_autoscaler ? 1 : 0

  source = "./cluster-autoscaler"

  cluster_name          = aws_eks_cluster.eks.name
  region                = var.region
  tags                  = var.tags
  cluster_iam_role_name = aws_iam_role.eks_cluster_role.name
  cluster_version       = var.eks_config.kubernetes_version
  auto_scaler_profile   = var.eks_config.auto_scaler_profile

  depends_on = [aws_eks_node_group.eks_managed_node_groups]
}

resource "terraform_data" "install_cni_metrics_helper" {
  count = var.eks_config.enable_cni_metrics_helper ? 1 : 0

  provisioner "local-exec" {
    command = <<EOT
      #!/bin/bash
      set -e
      helm repo add eks https://aws.github.io/eks-charts
      helm repo update eks
      aws eks update-kubeconfig --region ${var.region} --name ${local.eks_cluster_name}
      helm upgrade --install cni-metrics-helper --namespace kube-system eks/cni-metrics-helper  \
        --set "env.AWS_CLUSTER_ID=${local.eks_cluster_name}"

      EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
      #!/bin/bash
      set -e
      helm uninstall cni-metrics-helper --namespace kube-system

      EOT
  }
  depends_on = [module.eks_addon]
}