locals {
  autoscaler_namespace       = "kube-system"
  autoscaler_version         = "9.37.0"
  autoscaler_service_account = "cluster-autoscaler-sa"
  autoscaler_image_tag       = "v${var.cluster_version}.0"
}

data "aws_caller_identity" "current" {}

data "aws_iam_role" "cluster_role" {
  name = var.cluster_iam_role_name
}

resource "aws_iam_policy" "autoscaler_controller_policy" {
  name = substr("AutoscalerControllerPolicy-${var.cluster_name}", 0, 60)
  tags = var.tags
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AutoscalingResources"
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

resource "aws_iam_role_policy_attachment" "autoscaler_controller_policy_attachments" {
  policy_arn = aws_iam_policy.autoscaler_controller_policy.arn
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
      IMAGE_TAG    = local.autoscaler_image_tag
      CLUSTER_NAME = var.cluster_name
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


