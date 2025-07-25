locals {
  role               = var.eks_config.role
  eks_cluster_name   = "${var.eks_config.eks_name}-${var.run_id}"
  eks_node_group_map = { for node_group in var.eks_config.eks_managed_node_groups : node_group.name => node_group }

  eks_config_addons_map = { for addon in var.eks_config.eks_addons : addon.name => addon }

  eks_nodes_subnets_list = flatten([for node_group in var.eks_config.eks_managed_node_groups : node_group.subnet_names if node_group.subnet_names != null])

  karpenter_addons_map = {
    for addon in [
      { name = "vpc-cni", vpc_cni_warm_prefix_target = 1 },
      { name = "kube-proxy" },
      { name = "coredns" }
    ] : addon.name => addon
    if var.eks_config.enable_karpenter
  }

  # Merge all addon maps
  _eks_addons_map = merge(local.karpenter_addons_map, local.eks_config_addons_map)

  # Set default VPC-CNI settings if addon is present in the config
  vpc_cni_addon_map = contains(keys(local._eks_addons_map), "vpc-cni") ? {
    "vpc-cni" = {
      name           = "vpc-cni",
      policy_arns    = ["AmazonEKS_CNI_Policy"],
      before_compute = true, # ensure the vpc-cni is created and updated before any EC2 instances are created.
      configuration_values = {
        env = {
          # Enable IPv4 prefix delegation to increase the number of available IP addresses on the provisioned EC2 nodes.
          # This significantly increases number of pods that can be run per node. (see: https://aws.amazon.com/blogs/containers/amazon-vpc-cni-increases-pods-per-node-limits/)
          # Nodes must be AWS Nitro-based (see: https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-nitro-instances.html#nitro-instance-types)
          # Note: we've seen that it also prevents ENIs leak caused the issue: https://github.com/aws/amazon-vpc-cni-k8s/issues/608
          ENABLE_PREFIX_DELEGATION = "true"

          # Should set either WARM_PREFIX_TARGET or both MINIMUM_IP_TARGET and WARM_IP_TARGET (see: https://github.com/aws/amazon-vpc-cni-k8s/blob/master/docs/prefix-and-ip-target.md)
          WARM_PREFIX_TARGET = tostring(local._eks_addons_map["vpc-cni"].vpc_cni_warm_prefix_target)

          ADDITIONAL_ENI_TAGS = jsonencode(var.tags)
        }
      }
    }
  } : {}

  eks_addons_map = merge(local._eks_addons_map, local.vpc_cni_addon_map) # note: the order matters (the later takes precedence)

  auto_mode_policies = var.eks_config.auto_mode ? [
    "AmazonEKSBlockStoragePolicy",
    "AmazonEKSComputePolicy",
    "AmazonEKSLoadBalancingPolicy",
    "AmazonEKSWorkerNodeMinimalPolicy",
    "AmazonEKSNetworkingPolicy"
  ] : []

  policy_arns = concat(var.eks_config.policy_arns, local.auto_mode_policies)

  addons_policy_arns  = flatten([for addon in local.eks_addons_map : addon.policy_arns if can(addon.policy_arns)])
  service_account_map = { for addon in local.eks_addons_map : addon.name => addon.service_account if try(addon.service_account, null) != null }
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

data "aws_subnet" "subnet_details" {
  for_each = toset(local.eks_nodes_subnets_list)

  filter {
    name   = "tag:run_id"
    values = [var.run_id]
  }

  filter {
    name   = "tag:Name"
    values = [each.value]
  }
}


data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com", "ec2.amazonaws.com"]
    }

    actions = [
      "sts:AssumeRole",
      "sts:TagSession" # Required for EKS Auto Mode
    ]
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

  # Enable EKS Auto Mode (see: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_cluster#eks-cluster-with-eks-auto-mode)
  # When using EKS Auto Mode compute_config.enabled, kubernetes_network_config.elastic_load_balancing.enabled, 
  # and storage_config.block_storage.enabled must *ALL be set to true.
  # Enabling EKS Auto Mode also requires that bootstrap_self_managed_addons is set to false.

  bootstrap_self_managed_addons = var.eks_config.auto_mode ? false : true
  dynamic "compute_config" {
    for_each = var.eks_config.auto_mode ? { "compute_config" : true } : {}
    content {
      enabled = true
      # node_pools must be null. Custom node pools are created below.
    }
  }
  dynamic "storage_config" {
    for_each = var.eks_config.auto_mode ? { "block_storage" : true } : {}
    content {
      block_storage {
        enabled = true
      }
    }
  }
  dynamic "kubernetes_network_config" {
    for_each = var.eks_config.auto_mode ? { "elastic_load_balancing" : true } : {}
    content {
      elastic_load_balancing {
        enabled = true
      }
    }
  }

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

resource "aws_launch_template" "launch_template" {
  for_each = local.eks_node_group_map

  name = "${local.eks_cluster_name}-${each.value.name}"

  tag_specifications {
    resource_type = "instance"
    tags          = var.tags
  }

  user_data = var.user_data_path != "" ? filebase64("${var.user_data_path}/${local.role}-userdata.sh") : null

  network_interfaces {
    dynamic "ena_srd_specification" {
      for_each = var.ena_express != null || each.value.ena_express != null ? { "ena_express" : each.value.ena_express } : {}
      content {
        ena_srd_enabled = var.ena_express != null ? var.ena_express : each.value.ena_express
        ena_srd_udp_specification {
          ena_srd_udp_enabled = var.ena_express != null ? var.ena_express : each.value.ena_express
        }
      }
    }
  }

  dynamic "block_device_mappings" {
    for_each = each.value.block_device_mappings

    content {
      device_name = try(block_device_mappings.value.device_name, null)

      dynamic "ebs" {
        for_each = try([block_device_mappings.value.ebs], [])

        content {
          delete_on_termination = try(ebs.value.delete_on_termination, null)
          iops                  = try(ebs.value.iops, null)
          throughput            = try(ebs.value.throughput, null)
          volume_size           = try(ebs.value.volume_size, null)
          volume_type           = try(ebs.value.volume_type, null)
        }
      }
    }
  }

  tags = var.tags
}

resource "aws_eks_node_group" "eks_managed_node_groups" {

  for_each = local.eks_node_group_map

  node_group_name = each.value.name
  cluster_name    = aws_eks_cluster.eks.name
  node_role_arn   = aws_iam_role.eks_cluster_role.arn
  subnet_ids      = each.value.subnet_names != null ? toset([for subnet_name in each.value.subnet_names : data.aws_subnet.subnet_details[subnet_name].id]) : toset(data.aws_subnets.subnets.ids)

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
  instance_types = var.k8s_machine_type != null ? [var.k8s_machine_type] : each.value.instance_types
  capacity_type  = each.value.capacity_type
  labels         = each.value.labels

  launch_template {
    id      = aws_launch_template.launch_template[each.key].id
    version = aws_launch_template.launch_template[each.key].latest_version
  }

  tags = {
    "Name" = each.value.name
  }
  depends_on = [
    aws_eks_cluster.eks,
    aws_iam_role_policy_attachment.policy_attachments,
    aws_eks_addon.before_compute
  ]
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

################################################################################
# EKS Addons
################################################################################

data "aws_iam_policy_document" "addon_assume_role_policy" {
  count = length(local.eks_addons_map) != 0 ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    condition {
      test     = "StringLike"
      variable = "${replace(aws_iam_openid_connect_provider.oidc_provider.url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }

    dynamic "condition" {
      for_each = local.service_account_map
      content {
        test     = "StringLike"
        variable = "${replace(aws_iam_openid_connect_provider.oidc_provider.url, "https://", "")}:sub"
        values   = ["system:serviceaccount:kube-system:${condition.value}"]
      }
    }

    principals {
      identifiers = [aws_iam_openid_connect_provider.oidc_provider.arn]
      type        = "Federated"
    }
  }

  depends_on = [aws_iam_openid_connect_provider.oidc_provider]
}

resource "aws_iam_role" "addon_role" {
  count = length(local.eks_addons_map) != 0 ? 1 : 0

  assume_role_policy = data.aws_iam_policy_document.addon_assume_role_policy[0].json

  depends_on = [data.aws_iam_policy_document.addon_assume_role_policy]
}

resource "aws_iam_role_policy_attachment" "addon_policy_attachments" {
  for_each = toset(local.addons_policy_arns)

  policy_arn = "arn:aws:iam::aws:policy/${each.value}"
  role       = aws_iam_role.addon_role[0].name
  depends_on = [aws_iam_role.addon_role]
}

resource "aws_eks_addon" "addon" {
  for_each = { for k, v in local.eks_addons_map : k => v if !try(v.before_compute, false) }

  cluster_name             = aws_eks_cluster.eks.name
  addon_name               = each.value.name
  addon_version            = try(each.value.version, null)
  service_account_role_arn = aws_iam_role.addon_role[0].arn
  configuration_values     = try(each.value.configuration_values, null) != null ? jsonencode(each.value.configuration_values) : null

  tags = {
    "Name" = each.value.name
  }

  resolve_conflicts_on_create = "OVERWRITE"

  dynamic "timeouts" {
    for_each = try(each.value.timeouts, {}) != {} ? [each.value.timeouts] : []
    content {
      create = try(timeouts.value.create, "20m")
      update = try(timeouts.value.update, "20m")
      delete = try(timeouts.value.delete, "40m")
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.addon_policy_attachments,
    aws_eks_node_group.eks_managed_node_groups,
    terraform_data.apply_nodepool_system_custom,
    terraform_data.apply_nodepool_general_custom,
  ]
}

resource "aws_eks_addon" "before_compute" {
  for_each = { for k, v in local.eks_addons_map : k => v if try(v.before_compute, false) }

  cluster_name             = aws_eks_cluster.eks.name
  addon_name               = each.value.name
  addon_version            = try(each.value.version, null)
  service_account_role_arn = aws_iam_role.addon_role[0].arn
  configuration_values     = try(each.value.configuration_values, null) != null ? jsonencode(each.value.configuration_values) : null

  tags = {
    "Name" = each.value.name
  }

  depends_on = [aws_iam_role_policy_attachment.addon_policy_attachments]
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
  depends_on = [aws_eks_cluster.eks]
}



################################################################################
# EKS Auto Mode
################################################################################

resource "terraform_data" "apply_nodeclass_custom" {
  count = var.eks_config.auto_mode && (var.eks_config.node_pool_system || var.eks_config.node_pool_general_purpose) ? 1 : 0

  provisioner "local-exec" {
    command = <<EOT
      set -e
      aws eks update-kubeconfig --region ${var.region} --name ${local.eks_cluster_name}
      envsubst < "${path.module}/auto_mode/nodeclass-custom.yaml" | kubectl apply -f -
      # Wait for the nodeclass to be ready
      kubectl wait --for=condition=Ready nodeclass/custom --timeout=30s
      kubectl get nodeclass custom
    EOT
    environment = {
      RUN_ID            = var.tags["run_id"]
      OWNER             = var.tags["owner"]
      SCENARIO          = var.tags["scenario"]
      DELETION_DUE_TIME = var.tags["deletion_due_time"]
      NODE_ROLE_NAME    = aws_iam_role.eks_cluster_role.name
    }
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
      set -e
      kubectl delete nodeclass custom --ignore-not-found
    EOT
  }

  depends_on = [
    aws_eks_cluster.eks,
    aws_iam_role_policy_attachment.automode_controller_policy_attachments,
    aws_eks_access_entry.node_pool_entry,
    aws_eks_access_policy_association.node_pool_policy,
  ]
}

resource "terraform_data" "apply_nodepool_system_custom" {
  count = var.eks_config.auto_mode && var.eks_config.node_pool_system ? 1 : 0

  provisioner "local-exec" {
    command = <<EOT
      set -e
      kubectl apply -f "${path.module}/auto_mode/nodepool-system-custom.yaml"
      # Wait for the nodepool to be ready
      kubectl wait --for=condition=Ready nodepool/system-custom --timeout=30s
      kubectl get nodepool system-custom
    EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
      set -e
      kubectl delete nodepool system-custom --ignore-not-found
    EOT
  }

  depends_on = [terraform_data.apply_nodeclass_custom]
}

resource "terraform_data" "apply_nodepool_general_custom" {
  count = var.eks_config.auto_mode && var.eks_config.node_pool_general_purpose ? 1 : 0

  provisioner "local-exec" {
    command = <<EOT
      set -e
      kubectl apply -f "${path.module}/auto_mode/nodepool-general-custom.yaml"
      # Wait for the nodepool to be ready
      kubectl wait --for=condition=Ready nodepool/general-purpose-custom --timeout=30s
      kubectl get nodepool general-purpose-custom
    EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
      set -e
      kubectl delete nodepool general-purpose-custom --ignore-not-found
    EOT
  }

  depends_on = [terraform_data.apply_nodeclass_custom]
}

resource "aws_iam_policy" "automode_controller_policy" {
  count = var.eks_config.auto_mode && (var.eks_config.node_pool_system || var.eks_config.node_pool_general_purpose) ? 1 : 0

  name = substr("AutoModeControllerPolicy-${local.eks_cluster_name}", 0, 60)
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowScopedEC2InstanceAccessActions"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances",
          "ec2:CreateLaunchTemplate",
          "ec2:CreateTags",
          "ec2:CreateFleet",
          "ec2:DeleteLaunchTemplate"
        ]
        Resource = "*"
      },
      {
        Sid    = "AmazonEC2ContainerRegistryPullOnly"
        Effect = "Allow",
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchImportUpstreamImage"
        ],
        Resource : "*"
      },
      {
        Sid    = "AllowRegionalReadActions"
        Effect = "Allow"
        Action = [
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeImages",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceTypeOfferings",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplates",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeSpotPriceHistory",
          "ec2:DescribeSubnets"
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowEKSSSMReadActions"
        Effect = "Allow"
        Action = "ssm:GetParameter"
        Resource = [
          "arn:aws:ssm:${var.region}::parameter/aws/service/eks/optimized-ami/*",
          "arn:aws:ssm:${var.region}::parameter/aws/service/bottlerocket/*"
        ]
      },
      {
        Sid      = "AllowPricingReadActions"
        Effect   = "Allow"
        Action   = "pricing:GetProducts"
        Resource = "*"
      },
      {
        Sid      = "AllowPassingNodeRole"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = "arn:aws:iam::*:role/*eks*"
      },
      {
        Sid    = "AllowScopedInstanceProfileActions"
        Effect = "Allow"
        Action = [
          "iam:AddRoleToInstanceProfile",
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:TagInstanceProfile"
        ]
        Resource = "*"
      },
      {
        Sid      = "AllowClusterEndpointDiscovery"
        Effect   = "Allow"
        Action   = "eks:DescribeCluster"
        Resource = "arn:aws:eks:${var.region}:*:cluster/${local.eks_cluster_name}"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "automode_controller_policy_attachments" {
  count      = var.eks_config.auto_mode && (var.eks_config.node_pool_system || var.eks_config.node_pool_general_purpose) ? 1 : 0
  policy_arn = aws_iam_policy.automode_controller_policy[0].arn
  role       = aws_iam_role.eks_cluster_role.name
}

resource "aws_eks_access_entry" "node_pool_entry" {
  count         = var.eks_config.auto_mode && (var.eks_config.node_pool_system || var.eks_config.node_pool_general_purpose) ? 1 : 0
  cluster_name  = local.eks_cluster_name
  principal_arn = aws_iam_role.eks_cluster_role.arn
  type          = "EC2"
  depends_on    = [aws_eks_cluster.eks]
}

resource "aws_eks_access_policy_association" "node_pool_policy" {
  count         = var.eks_config.auto_mode && (var.eks_config.node_pool_system || var.eks_config.node_pool_general_purpose) ? 1 : 0
  cluster_name  = local.eks_cluster_name
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSAutoNodePolicy"
  principal_arn = aws_iam_role.eks_cluster_role.arn

  access_scope {
    type = "cluster"
  }
  depends_on = [aws_eks_access_entry.node_pool_entry]
}

# Deploy Metrics Server addon with manifest because the official EKS addon may take several hours to report healthy status when using EKS Auto Mode.
# AWS documentation: https://docs.aws.amazon.com/eks/latest/userguide/metrics-server.html
resource "terraform_data" "apply_metrics_server_addon" {
  # if EKS Auto Mode is enabled and metrics-server is not set in the addon list
  count = var.eks_config.auto_mode && !contains(keys(local.eks_addons_map), "metrics-server") ? 1 : 0

  provisioner "local-exec" {
    command = <<EOT
      set -e
      kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
      # Wait for the metrics-server deployment to be ready
      kubectl wait --for=condition=Available deployment/metrics-server -n kube-system --timeout=300s
      kubectl get pod -l k8s-app=metrics-server -n kube-system
    EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
      set -e
      kubectl delete -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
      # Wait for the deployment/metrics-server to be deleted
      kubectl wait --for=delete deployment/metrics-server -n kube-system --timeout=30s
    EOT
  }

  depends_on = [
    terraform_data.apply_nodepool_system_custom,
    terraform_data.apply_nodepool_general_custom
  ]
}