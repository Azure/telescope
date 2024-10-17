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
