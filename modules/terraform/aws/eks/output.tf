output "endpoint" {
  description = "value of the EKS endpoint"
  value       = aws_eks_cluster.eks.endpoint
}

output "dependencies" {
  description = "value of the EKS dependencies"
  value = {
    policy_attachments = aws_iam_role_policy_attachment.policy_attachments[*]
  }
}


output "eks_addon" {
  description = "EKS addon configuration. Used for unit tests"
  value = {
    after_compute : aws_eks_addon.addon,
    before_compute : aws_eks_addon.before_compute
  }
}

output "eks_node_groups_launch_template" {
  value = aws_launch_template.launch_template
}

output "eks_node_groups" {
  description = "Used for unit tests"
  value       = aws_eks_node_group.eks_managed_node_groups
}

output "eks_cluster" {
  description = "Used for unit tests"
  value       = aws_eks_cluster.eks
}

output "eks_role_policy_attachments" {
  description = "Used for unit tests"
  value       = aws_iam_role_policy_attachment.policy_attachments
}