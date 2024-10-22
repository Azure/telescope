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

data "aws_eks_cluster" "cluster" {
  name = var.cluster_name
}

resource "aws_ec2_tag" "cluster_primary_security_group" {
  resource_id = data.aws_eks_cluster.cluster.vpc_config[0].cluster_security_group_id
  key         = "karpenter.sh/discovery"
  value       = var.cluster_name
}

resource "aws_iam_policy" "autoscaler_controller_policy" {
  name = substr("AutoscalerControllerPolicy-${var.cluster_name}", 0, 60)
  tags = var.tags
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DescribeAutoscalingResources"
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
          "eks:DescribeNodegroup"
        ]
      },
      {
        Sid      = "ManageAutoScaling"
        Effect   = "Allow"
        Resource = "arn:aws:ec2:${var.region}:*:launch-template/*"
        Action = [
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup"
        ]
        Condition = {
          "StringEquals" = {
            "aws:ResourceTag/k8s.io/cluster-autoscaler/enabled"             = "true",
            "aws:ResourceTag/k8s.io/cluster-autoscaler/${var.cluster_name}" = "owned"
          }
        }
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
      # Install autoscaler
      helm registry logout public.ecr.aws || true
			helm repo add autoscaler https://kubernetes.github.io/autoscaler
			helm upgrade --install cluster-autoscaler autoscaler/cluster-autoscaler \
				--version "${local.autoscaler_version}" \
				--namespace "${local.autoscaler_namespace}" \
				--set "autoDiscovery.clusterName=${var.cluster_name}" \
				--set "awsRegion=${var.region}" \
				--set "image.tag=${local.autoscaler_image_tag}" \
				--set "rbac.serviceAccount.name=${local.autoscaler_service_account}" \
				--set "rbac.serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"="${var.cluster_iam_role_name}" \
				--wait

      EOT
    environment = {
      ROLE_NAME         = var.cluster_iam_role_name
      RUN_ID            = var.tags["run_id"]
      OWNER             = var.tags["owner"]
      SCENARIO          = var.tags["scenario"]
      DELETION_DUE_TIME = var.tags["deletion_due_time"]
      CLUSTER_NAME      = var.cluster_name
    }
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
      #!/bin/bash
      set -e
      helm uninstall autoscaler --namespace kube-system

      EOT
  }
}
