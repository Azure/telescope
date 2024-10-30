locals {
  autoscaler_image_tag = "v${var.cluster_version}.0"
}

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

resource "aws_iam_role_policy_attachment" "autoscaler_policy_attachments" {
  policy_arn = aws_iam_policy.autoscaler_policy.arn
  role       = var.cluster_iam_role_name
}

resource "terraform_data" "install_autoscaler" {
  provisioner "local-exec" {
    command = <<EOT
      #!/bin/bash
      set -e
      aws eks --region ${var.region} update-kubeconfig --name "${var.cluster_name}"
			envsubst  < "${path.module}/autoscaler.yml" | kubectl apply -f -

      EOT
    environment = {
      IMAGE_TAG                        = local.autoscaler_image_tag
      CLUSTER_NAME                     = var.cluster_name
      BALANCE_SIMILAR_NODE_GROUPS      = var.auto_scaler_profile.balance_similar_node_groups
      EXPANDER                         = var.auto_scaler_profile.expander
      MAX_GRACEFUL_TERMINATION_SEC     = var.auto_scaler_profile.max_graceful_termination_sec
      MAX_NODE_PROVISION_TIME          = var.auto_scaler_profile.max_node_provision_time
      MAX_UNREADY_NODES                = var.auto_scaler_profile.max_unready_nodes
      MAX_UNREADY_PERCENTAGE           = var.auto_scaler_profile.max_unready_percentage
      NEW_POD_SCALE_UP_DELAY           = var.auto_scaler_profile.new_pod_scale_up_delay
      SCALE_DOWN_DELAY_AFTER_ADD       = var.auto_scaler_profile.scale_down_delay_after_add
      SCALE_DOWN_DELAY_AFTER_DELETE    = var.auto_scaler_profile.scale_down_delay_after_delete
      SCALE_DOWN_DELAY_AFTER_FAILURE   = var.auto_scaler_profile.scale_down_delay_after_failure
      SCALE_DOWN_UNNEEDED              = var.auto_scaler_profile.scale_down_unneeded
      SCALE_DOWN_UNREADY               = var.auto_scaler_profile.scale_down_unready
      SCALE_DOWN_UTILIZATION_THRESHOLD = var.auto_scaler_profile.scale_down_utilization_threshold
      SCAN_INTERVAL                    = var.auto_scaler_profile.scan_interval
      EMPTY_BULK_DELETE_MAX            = var.auto_scaler_profile.empty_bulk_delete_max
      SKIP_NODES_WITH_LOCAL_STORAGE    = var.auto_scaler_profile.skip_nodes_with_local_storage
      SKIP_NODES_WITH_SYSTEM_PODS      = var.auto_scaler_profile.skip_nodes_with_system_pods
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
