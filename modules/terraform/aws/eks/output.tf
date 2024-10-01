output "endpoint" {
  description = "value of the EKS endpoint"
  value       = aws_eks_cluster.eks.endpoint
}

output "oidc_provider_arn" {
  description = "value of the EKS OIDC provider ARN"
  value       = aws_iam_openid_connect_provider.oidc_provider.arn
}