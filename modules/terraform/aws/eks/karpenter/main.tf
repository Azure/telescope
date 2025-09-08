locals {
  karpenter_namespace = "kube-system"
  karpenter_version   = "1.0.3"

  # Parse the cluster version to determine AMI family
  # For k8s 1.32 and below: al2@latest with AL2 family
  # For k8s 1.33 and above: al2023@latest with AL2023 family
  cluster_version_parts = split(".", var.cluster_version)
  cluster_major_version = tonumber(local.cluster_version_parts[0])
  cluster_minor_version = tonumber(local.cluster_version_parts[1])

  # Determine AMI alias and family based on version
  is_k8s_133_or_above = (local.cluster_major_version == 1 && local.cluster_minor_version >= 33)
  ami_alias           = local.is_k8s_133_or_above ? "al2023@latest" : "al2@latest"
  ami_family          = local.is_k8s_133_or_above ? "AL2023" : "AL2"
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

# IAM role for Karpenter service account (IRSA)
resource "aws_iam_role" "karpenter_role" {
  name = substr("KarpenterRole-${var.cluster_name}", 0, 64)
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
            "${replace(data.aws_eks_cluster.cluster.identity[0].oidc[0].issuer, "https://", "")}:sub" = "system:serviceaccount:kube-system:karpenter"
            "${replace(data.aws_eks_cluster.cluster.identity[0].oidc[0].issuer, "https://", "")}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "karpenter_controller_policy_attachments" {
  policy_arn = aws_iam_policy.karpenter_controller_policy.arn
  role       = aws_iam_role.karpenter_role.name
}

resource "terraform_data" "install_karpenter" {
  provisioner "local-exec" {
    command = <<EOT
      #!/bin/bash
      set -e
      aws eks --region ${var.region} update-kubeconfig --name "${var.cluster_name}"
      # Install Karpenter with IRSA
      helm registry logout public.ecr.aws || true
      helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
        --version "${local.karpenter_version}" \
        --namespace "${local.karpenter_namespace}" \
        --set "settings.clusterName=${var.cluster_name}" \
        --set "serviceAccount.annotations.eks\.amazonaws\.com/role-arn=${aws_iam_role.karpenter_role.arn}" \
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
      AMI_ALIAS         = local.ami_alias
      AMI_FAMILY        = local.ami_family
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
