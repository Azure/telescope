locals {
  karpenter_namespace       = "kube-system"
  karpenter_service_account = "karpenter"
}

data "aws_caller_identity" "current" {}

data "aws_iam_role" "cluster_role" {
  name = var.cluster_iam_role_name
}

resource "aws_iam_role" "karpenter_node_role" {
  name = substr("KarpenterNodeRole-${var.cluster_name}", 0, 60)
  tags = var.tags
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  managed_policy_arns = [
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  ]
}

resource "aws_iam_policy" "karpenter_controller_policy" {
  name = substr("KarpenterControllerPolicy-${var.cluster_name}", 0, 60)
  tags = var.tags
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowScopedEC2InstanceAccessActions"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${var.region}::image/*",
          "arn:aws:ec2:${var.region}::snapshot/*",
          "arn:aws:ec2:${var.region}:*:security-group/*",
          "arn:aws:ec2:${var.region}:*:subnet/*"
        ]
        Action = [
          "ec2:RunInstances",
          "ec2:CreateFleet"
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
          "arn:aws:ec2:${var.region}:*:spot-instances-request/*"
        ]
        Action = [
          "ec2:RunInstances",
          "ec2:CreateFleet",
          "ec2:CreateLaunchTemplate"
        ]
        Condition = {
          "StringEquals" = {
            "aws:RequestTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:RequestTag/eks:eks-cluster-name"                      = var.cluster_name
          }
          "StringLike" = {
            "aws:RequestTag/karpenter.sh/nodepool" = "*"
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
          "arn:aws:ec2:${var.region}:*:spot-instances-request/*"
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
          "StringLike" = {
            "aws:RequestTag/karpenter.sh/nodepool" = "*"
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
            "aws:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "owned"
          }
          "StringLike" = {
            "aws:ResourceTag/karpenter.sh/nodepool" = "*"
          }
          "StringEqualsIfExists" = {
            "aws:RequestTag/eks:eks-cluster-name" = var.cluster_name
          }
          "ForAllValues:StringEquals" = {
            "aws:TagKeys" = [
              "eks:eks-cluster-name",
              "karpenter.sh/nodeclaim",
              "Name"
            ]
          }
        }
      },
      {
        Sid    = "AllowScopedDeletion"
        Effect = "Allow"
        Resource = [
          "arn:aws:ec2:${var.region}:*:instance/*",
          "arn:aws:ec2:${var.region}:*:launch-template/*"
        ]
        Action = [
          "ec2:TerminateInstances",
          "ec2:DeleteLaunchTemplate"
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
        Condition = {
          "StringEquals" = {
            "aws:RequestedRegion" = var.region
          }
        }
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
        Resource = [aws_iam_role.karpenter_node_role.arn, data.aws_iam_role.cluster_role.arn]
        Action   = "iam:PassRole"
        Condition = {
          "StringEquals" = {
            "iam:PassedToService" = "ec2.amazonaws.com"
          }
        }
      },
      {
        Sid      = "AllowScopedInstanceProfileCreationActions"
        Effect   = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action = [
          "iam:CreateInstanceProfile"
        ]
        Condition = {
          "StringEquals" = {
            "aws:RequestTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:RequestTag/eks:eks-cluster-name"                      = var.cluster_name,
            "aws:RequestTag/topology.kubernetes.io/region"             = var.region
          }
          "StringLike" = {
            "aws:RequestTag/karpenter.k8s.aws/ec2nodeclass" = "*"
          }
        }
      },
      {
        Sid      = "AllowScopedInstanceProfileTagActions"
        Effect   = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action = [
          "iam:TagInstanceProfile"
        ]
        Condition = {
          "StringEquals" = {
            "aws:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:ResourceTag/topology.kubernetes.io/region"             = var.region,
            "aws:RequestTag/eks:eks-cluster-name"                       = var.cluster_name
          }
          "StringLike" = {
            "aws:ResourceTag/karpenter.k8s.aws/ec2nodeclass" = "*"
          }
        }
      },
      {
        Sid      = "AllowScopedInstanceProfileActions"
        Effect   = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action = [
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:DeleteInstanceProfile"
        ]
        Condition = {
          "StringEquals" = {
            "aws:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:ResourceTag/topology.kubernetes.io/region"             = var.region
          }
          "StringLike" = {
            "aws:ResourceTag/karpenter.k8s.aws/ec2nodeclass" = "*"
          }
        }
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
        --version "1.0.3" \
        --namespace "kube-system" \
        --set "settings.clusterName=${var.cluster_name}" \
        --set controller.resources.requests.cpu=1 \
        --set controller.resources.requests.memory=1Gi \
        --set controller.resources.limits.cpu=1 \
        --set controller.resources.limits.memory=1Gi \
        --set replicas=1 \
        --wait
			sleep 10
			envsubst  < "${var.user_data_path}/NodeClass.yml" | kubectl apply -f -

			EOT
    environment = {
      ROLE_NAME = substr("KarpenterNodeRole-${var.cluster_name}", 0, 60)
      RUN_ID    = var.run_id
    }
  }

  provisioner "local-exec" {
    when    = destroy
    command = <<EOT
			#!/bin/bash
			set -e
			helm uninstall karpenter --namespace ${local.karpenter_namespace}
		  EOT
  }
}

resource "terraform_data" "update_aws_auth_config_map" {
  provisioner "local-exec" {
    command = <<EOT
			#!/bin/bash
			set -e
      kubectl get configmaps -n kube-system aws-auth -o yaml
		  ROLE="    - groups:\n      - system:bootstrappers\n      - system:nodes\n      rolearn: ${aws_iam_role.karpenter_node_role.arn}\n      username: system:node:{{EC2PrivateDNSName}}"

      kubectl get -n kube-system configmap/aws-auth -o yaml | awk "/mapRoles: \|/{print;print \"$ROLE\";next}1" > aws-auth-patch.yml
      kubectl patch configmap/aws-auth -n kube-system --patch "$(cat aws-auth-patch.yml)"

			EOT    
  }
}


resource "aws_iam_role" "karpenter" {
  name = substr("karpenter-${var.cluster_name}", 0, 60)

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        "Effect" : "Allow",
        "Principal" : {
          "Service" : [
            "pods.eks.amazonaws.com"
          ]
        },
        "Action" : [
          "sts:AssumeRole",
          "sts:TagSession"
        ]
      }
    ]
  })
  managed_policy_arns = [
    "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
    aws_iam_policy.karpenter_controller_policy.arn
  ]
  depends_on = [terraform_data.install_karpenter]
}

resource "aws_eks_pod_identity_association" "association" {
  cluster_name    = var.cluster_name
  namespace       = local.karpenter_namespace
  service_account = local.karpenter_service_account
  role_arn        = aws_iam_role.karpenter.arn
}
