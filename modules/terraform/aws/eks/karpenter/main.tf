locals {
  account_id                     = data.aws_caller_identity.current.account_id
  cluster_name                   = var.cluster_name
}

data "aws_caller_identity" "current" {}

data "aws_iam_role" "cluster_role" {
  name = var.cluster_iam_role_name
}

resource "aws_iam_role" "karpenter_node_role" {
  name = substr("KarpenterNodeRole-${var.cluster_name}", 0, 60)
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
  name        = substr("KarpenterControllerPolicy-${var.cluster_name}", 0, 60)
  policy      = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid = "AllowScopedEC2InstanceAccessActions"
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
        Sid = "AllowScopedEC2LaunchTemplateAccessActions"
        Effect = "Allow"
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
        Sid = "AllowScopedEC2InstanceActionsWithTags"
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
            "aws:RequestTag/eks:eks-cluster-name" = "${var.cluster_name}"
          }
          "StringLike" = {
            "aws:RequestTag/karpenter.sh/nodepool" = "*"
          }
        }
      },
      {
        Sid = "AllowScopedResourceCreationTagging"
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
            "aws:RequestTag/eks:eks-cluster-name" = "${var.cluster_name}",
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
        Sid = "AllowScopedResourceTagging"
        Effect = "Allow"
        Resource = "arn:aws:ec2:${var.region}:*:instance/*"
        Action = "ec2:CreateTags"
        Condition = {
          "StringEquals" = {
            "aws:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "owned"
          }
          "StringLike" = {
            "aws:ResourceTag/karpenter.sh/nodepool" = "*"
          }
          "StringEqualsIfExists" = {
            "aws:RequestTag/eks:eks-cluster-name" = "${var.cluster_name}"
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
        Sid = "AllowScopedDeletion"
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
        Sid = "AllowRegionalReadActions"
        Effect = "Allow"
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
            "aws:RequestedRegion" = "${var.region}"
          }
        }
      },
      {
        Sid = "AllowSSMReadActions"
        Effect = "Allow"
        Resource = "arn:aws:ssm:${var.region}::parameter/aws/service/*"
        Action = "ssm:GetParameter"
      },
      {
        Sid = "AllowPricingReadActions"
        Effect = "Allow"
        Resource = "*"
        Action = "pricing:GetProducts"
      },
      # {
      #   Sid = "AllowInterruptionQueueActions"
      #   Effect = "Allow"
      #   Resource = "${aws_sqs_queue.karpenter_interruption_queue.arn}"
      #   Action = [
      #     "sqs:DeleteMessage",
      #     "sqs:GetQueueUrl",
      #     "sqs:ReceiveMessage"
      #   ]
      # },
      {
        Sid = "AllowPassingInstanceRole"
        Effect = "Allow"
        Resource = [aws_iam_role.karpenter_node_role.arn, data.aws_iam_role.cluster_role.arn]
        Action = "iam:PassRole"
        Condition = {
          "StringEquals" = {
            "iam:PassedToService" = "ec2.amazonaws.com"
          }
        }
      },
      {
        Sid = "AllowScopedInstanceProfileCreationActions"
        Effect = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action = [
          "iam:CreateInstanceProfile"
        ]
        Condition = {
          "StringEquals" = {
            "aws:RequestTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:RequestTag/eks:eks-cluster-name" = "${var.cluster_name}",
            "aws:RequestTag/topology.kubernetes.io/region" = "${var.region}"
          }
          "StringLike" = {
            "aws:RequestTag/karpenter.k8s.aws/ec2nodeclass" = "*"
          }
        }
      },
      {
        Sid = "AllowScopedInstanceProfileTagActions"
        Effect = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action = [
          "iam:TagInstanceProfile"
        ]
        Condition = {
          "StringEquals" = {
            "aws:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:ResourceTag/topology.kubernetes.io/region" = "${var.region}",
            "aws:RequestTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:RequestTag/eks:eks-cluster-name" = "${var.cluster_name}",
            "aws:RequestTag/topology.kubernetes.io/region" = "${var.region}"
          }
          "StringLike" = {
            "aws:ResourceTag/karpenter.k8s.aws/ec2nodeclass" = "*"
          }
        }
      },
        {
        Sid = "AllowScopedInstanceProfileActions"
        Effect = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action = [
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:DeleteInstanceProfile"
        ]
        Condition = {
          "StringEquals" = {
            "aws:ResourceTag/kubernetes.io/cluster/${var.cluster_name}" = "owned",
            "aws:ResourceTag/topology.kubernetes.io/region" = "${var.region}"            
          }
          "StringLike" = {
            "aws:ResourceTag/karpenter.k8s.aws/ec2nodeclass" = "*"
          }
        }
      },
      {
        Sid = "AllowInstanceProfileReadActions"
        Effect = "Allow"
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
        Action = [
          "iam:GetInstanceProfile"
        ]
      },{
        Sid = "AllowAPIServerEndpointDiscovery"
        Effect = "Allow"
        Resource = "arn:aws:eks:${var.region}:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
        Action = "eks:DescribeCluster"
      }
    ]
  })
}

# resource "aws_sqs_queue" "karpenter_interruption_queue" {
#   name                      = var.cluster_name
#   message_retention_seconds = 300
#   sqs_managed_sse_enabled   = true
# }

# resource "aws_sqs_queue_policy" "karpenter_interruption_queue_policy" {
#   queue_url = aws_sqs_queue.karpenter_interruption_queue.id

#   policy = jsonencode({
#     Version = "2012-10-17"
#     Statement = [
#       {
#         Effect    = "Allow"
#         Principal = {
#           Service = [
#             "events.amazonaws.com",
#             "sqs.amazonaws.com"
#           ]
#         }
#         Action    = "sqs:SendMessage"
#         Resource  = aws_sqs_queue.karpenter_interruption_queue.arn
#       },
#       {
#         Sid       = "DenyHTTP"
#         Effect    = "Deny"
#         Action    = "sqs:*"
#         Resource  = aws_sqs_queue.karpenter_interruption_queue.arn
#         Condition = {
#           "Bool" = {
#             "aws:SecureTransport" = false
#           }
#         }
#         Principal = "*"
#       }
#     ]
#   })
#   depends_on = [ aws_sqs_queue.karpenter_interruption_queue ]
# }

# resource "aws_cloudwatch_event_rule" "scheduled_change_rule" {
#   name        = "ScheduledChangeRule"
#   description = "Triggers on AWS Health Events"
#   event_pattern = jsonencode({
#     source     = ["aws.health"]
#     "detail-type" = ["AWS Health Event"]
#   })
# }

# resource "aws_cloudwatch_event_rule" "spot_interruption_rule" {
#   name        = "SpotInterruptionRule"
#   description = "Triggers on EC2 Spot Instance Interruption Warnings"
#   event_pattern = jsonencode({
#     source     = ["aws.ec2"]
#     "detail-type" = ["EC2 Spot Instance Interruption Warning"]
#   })
# }

# resource "aws_cloudwatch_event_rule" "rebalance_rule" {
#   name        = "RebalanceRule"
#   description = "Triggers on EC2 Instance Rebalance Recommendations"
#   event_pattern = jsonencode({
#     source     = ["aws.ec2"]
#     "detail-type" = ["EC2 Instance Rebalance Recommendation"]
#   })
# }

# resource "aws_cloudwatch_event_rule" "instance_state_change_rule" {
#   name        = "InstanceStateChangeRule"
#   description = "Triggers on EC2 Instance State-change Notifications"
#   event_pattern = jsonencode({
#     source     = ["aws.ec2"]
#     "detail-type" = ["EC2 Instance State-change Notification"]
#   })
# }

# resource "aws_cloudwatch_event_target" "karpenter_interruption_queue_target" {
#   rule      = aws_cloudwatch_event_rule.scheduled_change_rule.name
#   arn       = aws_sqs_queue.karpenter_interruption_queue.arn
#   target_id = "KarpenterInterruptionQueueTarget"
# }

# resource "aws_cloudwatch_event_target" "spot_interruption_queue_target" {
#   rule      = aws_cloudwatch_event_rule.spot_interruption_rule.name
#   arn       = aws_sqs_queue.karpenter_interruption_queue.arn
#   target_id = "KarpenterInterruptionQueueTarget"
# }

# resource "aws_cloudwatch_event_target" "rebalance_queue_target" {
#   rule      = aws_cloudwatch_event_rule.rebalance_rule.name
#   arn       = aws_sqs_queue.karpenter_interruption_queue.arn
#   target_id = "KarpenterInterruptionQueueTarget"
# }

# resource "aws_cloudwatch_event_target" "instance_state_change_queue_target" {
#   rule      = aws_cloudwatch_event_rule.instance_state_change_rule.name
#   arn       = aws_sqs_queue.karpenter_interruption_queue.arn
#   target_id = "KarpenterInterruptionQueueTarget"
# }


resource "aws_iam_role_policy_attachment" "karpenter_controller_policy_attachments" {
  policy_arn = aws_iam_policy.karpenter_controller_policy.arn
  role       = var.cluster_iam_role_name
}


resource "terraform_data" "install_karpenter" {
  provisioner "local-exec" {
    command = <<EOT
			#!/bin/bash
			set -e
      aws eks --region ${var.region} update-kubeconfig --name "${local.cluster_name}"
      # Install Karpenter
      helm registry logout public.ecr.aws || true
      helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
        --version "1.0.3" \
        --namespace "kube-system" \
        --set "settings.clusterName=${local.cluster_name}" \
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
      EKS_CLUSTER_NAME = local.cluster_name
      RUN_ID = var.run_id
      REGION = var.region
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

resource "terraform_data" "update_aws_auth_config_map" {
  provisioner "local-exec" {
    command = <<EOT
			#!/bin/bash
			set -e
      kubectl get configmaps -n kube-system aws-auth -o yaml

		  ROLE="    - groups:\n      - system:bootstrappers\n      - system:nodes\n      rolearn: ${aws_iam_role.karpenter_node_role.arn}\n      username: system:node:{{EC2PrivateDNSName}}"

      kubectl get -n kube-system configmap/aws-auth -o yaml | awk "/mapRoles: \|/{print;print \"$ROLE\";next}1" > aws-auth-patch.yml
      kubectl patch configmap/aws-auth -n kube-system --patch "$(cat aws-auth-patch.yml)"
      # check configmap after patch
      kubectl get configmaps -n kube-system aws-auth -o yaml

			EOT    
  }
}


resource "aws_iam_role" "karpenter" {
  name = substr("karpenter-${var.cluster_name}", 0, 60)

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": [
                  "pods.eks.amazonaws.com"
                ]
            },
            "Action": [
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
  depends_on = [ terraform_data.install_karpenter ]
}

resource "aws_eks_pod_identity_association" "association" {
  cluster_name    = local.cluster_name
  namespace       = var.karpenter_namespace
  service_account = "karpenter"
  role_arn        = aws_iam_role.karpenter.arn
}

