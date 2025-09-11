locals {
  autoscaler_image_tag = "v${var.cluster_version}.0"
}

# Data source to get the OIDC provider details
data "aws_eks_cluster" "cluster" {
  name = var.cluster_name
}

# IAM policy for cluster autoscaler
resource "aws_iam_policy" "autoscaler_policy" {
  name = substr("AutoscalerPolicy-${var.cluster_name}", 0, 60)
  tags = var.tags
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PermitAutoScaling"
        Effect   = "Allow"
        Resource = "*"
        Action = [
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:DescribeAutoScalingInstances",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:DescribeScalingActivities",
          "autoscaling:DescribeTags",
          "ec2:DescribeImages",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeLaunchTemplateVersions",
          "ec2:GetInstanceTypesFromInstanceRequirements",
          "eks:DescribeNodegroup",
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup"
        ]
      }
    ]
  })
}

# IAM role for cluster autoscaler service account (IRSA)
resource "aws_iam_role" "autoscaler_role" {
  name = substr("ClusterAutoscalerRole-${var.cluster_name}", 0, 64)
  tags = var.tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = var.oidc_provider_arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${replace(data.aws_eks_cluster.cluster.identity[0].oidc[0].issuer, "https://", "")}:sub" = "system:serviceaccount:kube-system:cluster-autoscaler"
            "${replace(data.aws_eks_cluster.cluster.identity[0].oidc[0].issuer, "https://", "")}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })
}

# Attach the policy to the IAM role
resource "aws_iam_role_policy_attachment" "autoscaler_policy_attachments" {
  policy_arn = aws_iam_policy.autoscaler_policy.arn
  role       = aws_iam_role.autoscaler_role.name
}

resource "terraform_data" "install_autoscaler" {
  provisioner "local-exec" {
    command = <<EOT
      #!/bin/bash
      set -e
      aws eks --region ${var.region} update-kubeconfig --name "${var.cluster_name}"
			envsubst  < "${path.module}/autoscaler.yml" | kubectl apply -f -

      kubectl wait --for=condition=Ready pod -l app=cluster-autoscaler -n kube-system --timeout=180s

      EOT
    environment = {
      AWS_REGION                       = var.region
      IMAGE_TAG                        = local.autoscaler_image_tag
      CLUSTER_NAME                     = var.cluster_name
      IRSA_ROLE_ARN                    = aws_iam_role.autoscaler_role.arn
      BALANCE_SIMILAR_NODE_GROUPS      = try(var.auto_scaler_profile.balance_similar_node_groups, false)
      EXPANDER                         = try(var.auto_scaler_profile.expander, "random")
      MAX_GRACEFUL_TERMINATION_SEC     = try(var.auto_scaler_profile.max_graceful_termination_sec, "600")
      MAX_NODE_PROVISION_TIME          = try(var.auto_scaler_profile.max_node_provision_time, "15m")
      MAX_UNREADY_NODES                = try(var.auto_scaler_profile.max_unready_nodes, 3)
      MAX_UNREADY_PERCENTAGE           = try(var.auto_scaler_profile.max_unready_percentage, 45)
      NEW_POD_SCALE_UP_DELAY           = try(var.auto_scaler_profile.new_pod_scale_up_delay, "10s")
      SCALE_DOWN_DELAY_AFTER_ADD       = try(var.auto_scaler_profile.scale_down_delay_after_add, "10m")
      SCALE_DOWN_DELAY_AFTER_DELETE    = try(var.auto_scaler_profile.scale_down_delay_after_delete, "10m")
      SCALE_DOWN_DELAY_AFTER_FAILURE   = try(var.auto_scaler_profile.scale_down_delay_after_failure, "3m")
      SCALE_DOWN_UNNEEDED              = try(var.auto_scaler_profile.scale_down_unneeded, "10m")
      SCALE_DOWN_UNREADY               = try(var.auto_scaler_profile.scale_down_unready, "20m")
      SCALE_DOWN_UTILIZATION_THRESHOLD = try(var.auto_scaler_profile.scale_down_utilization_threshold, "0.5")
      SCAN_INTERVAL                    = try(var.auto_scaler_profile.scan_interval, "10s")
      EMPTY_BULK_DELETE_MAX            = try(var.auto_scaler_profile.empty_bulk_delete_max, "10")
      SKIP_NODES_WITH_LOCAL_STORAGE    = try(var.auto_scaler_profile.skip_nodes_with_local_storage, true)
      SKIP_NODES_WITH_SYSTEM_PODS      = try(var.auto_scaler_profile.skip_nodes_with_system_pods, true)
    }
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
      #!/bin/bash
      set -e
      kubectl delete deployment -n kube-system cluster-autoscaler

      EOT
  }
}
