locals {
  karpenter_namespace = "kube-system"
  karpenter_version   = "1.0.3"
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

resource "aws_iam_policy" "karpenter_controller_policy" {
  name = substr("KarpenterControllerPolicy-${var.cluster_name}", 0, 60)
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowScopedEC2InstanceAccessActions"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${var.region}::image/*",
          "arn:aws:ec2:*::snapshot/*",
          "arn:aws:ec2:${var.region}:*:security-group/*",
          "arn:aws:ec2:${var.region}:*:subnet/*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:*",
          "arn:aws:ec2:${var.region}:*:launch-template/*",
        ]
        Action = [
          "ec2:RunInstances",
          "ec2:CreateLaunchTemplate",
          "ec2:CreateTags",
          "ec2:CreateFleet",
          "ec2:DeleteLaunchTemplate"
        ]
      },
      {
        Sid      = "AllowScopedEC2LaunchTemplateAccessActions"
        Effect   = "Allow"
        Resource = "arn:aws:ec2:${var.region}:*:launch-template/*"
        Action = [
          "ec2:RunInstances",
          "ec2:CreateFleet"
        ]
        Condition = {
          "StringEquals" = {
            "aws:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "owned"
          }
          "StringLike" = {
            "aws:ResourceTag/karpenter.sh/nodepool" = "*"
          }
        }
      },
      {
        Sid    = "AllowScopedEC2InstanceActionsWithTags"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${var.region}:*:fleet/*",
          "arn:aws:ec2:${var.region}:*:instance/*",
          "arn:aws:ec2:${var.region}:*:volume/*",
          "arn:aws:ec2:${var.region}:*:network-interface/*",
          "arn:aws:ec2:${var.region}:*:launch-template/*",
        ]
        Action = [
          "ec2:RunInstances",
          "ec2:CreateFleet",
          "ec2:CreateLaunchTemplate",
          "ec2:DeleteLaunchTemplate"
        ]
        Condition = {
          "StringEquals" = {
            "aws:RequestTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:RequestTag/eks:eks-cluster-name"                      = var.cluster_name
          }
        }
      },
      {
        Sid    = "AllowScopedResourceCreationTagging"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${var.region}:*:fleet/*",
          "arn:aws:ec2:${var.region}:*:instance/*",
          "arn:aws:ec2:${var.region}:*:volume/*",
          "arn:aws:ec2:${var.region}:*:network-interface/*",
          "arn:aws:ec2:${var.region}:*:launch-template/*",
        ]
        Action = "ec2:CreateTags"
        Condition = {
          "StringEquals" = {
            "aws:RequestTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:RequestTag/eks:eks-cluster-name"                      = var.cluster_name,
            "ec2:CreateAction" = [
              "RunInstances",
              "CreateFleet",
              "CreateLaunchTemplate"
            ]
          }
        }
      },
      {
        Sid      = "AllowScopedResourceTagging"
        Effect   = "Allow"
        Resource = "arn:aws:ec2:${var.region}:*:instance/*"
        Action   = "ec2:CreateTags"
        Condition = {
          "StringEquals" = {
            "aws:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "*"
          }
          "StringEqualsIfExists" = {
            "aws:RequestTag/eks:eks-cluster-name" = var.cluster_name
          }
        }
      },
      {
        Sid    = "AllowScopedDeletion"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${var.region}:*:instance/*",
        ]
        Action = [
          "ec2:TerminateInstances",
        ]
        Condition = {
          "StringLike" = {
            "ec2:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "*"
          }
        }
      },
      {
        Sid      = "AllowRegionalReadActions"
        Effect   = "Allow"
        Resource = "*"
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
      },
      {
        Sid      = "AllowSSMReadActions"
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${var.region}::parameter/aws/service/*"
        Action   = "ssm:GetParameter"
      },
      {
        Sid      = "AllowPricingReadActions"
        Effect   = "Allow"
        Resource = "*"
        Action   = "pricing:GetProducts"
      },
      {
        Sid      = "AllowPassingInstanceRole"
        Effect   = "Allow"
        Resource = [data.aws_iam_role.cluster_role.arn]
        Action   = "iam:PassRole"
      },
      {
        Sid      = "AllowScopedInstanceProfileActions"
        Effect   = "Allow"
        Resource = "*"
        Action = [
          "iam:AddRoleToInstanceProfile",
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:TagInstanceProfile",
        ]
      },
      {
        Sid      = "AllowInstanceProfileReadActions"
        Effect   = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action = [
          "iam:GetInstanceProfile"
        ]
        }, {
        Sid      = "AllowAPIServerEndpointDiscovery"
        Effect   = "Allow"
        Resource = "arn:aws:eks:${var.region}:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
        Action   = "eks:DescribeCluster"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "karpenter_controller_policy_attachments" {
  policy_arn = aws_iam_policy.karpenter_controller_policy.arn
  role       = var.cluster_iam_role_name
}

resource "terraform_data" "install_karpenter" {
  provisioner "local-exec" {
    command = <<EOT
      #!/bin/bash
      set -e
      aws eks --region ${var.region} update-kubeconfig --name "${var.cluster_name}"
      # Install Karpenter
      helm registry logout public.ecr.aws || true
      helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
        --version "${local.karpenter_version}" \
        --namespace "${local.karpenter_namespace}" \
        --set "settings.clusterName=${var.cluster_name}" \
        --wait
      sleep 10
      envsubst  < "${path.module}/NodeClass.yml" | kubectl apply -f -
      kubectl get ec2nodeclass default -o yaml

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
      helm uninstall karpenter --namespace kube-system

      EOT
  }
}
