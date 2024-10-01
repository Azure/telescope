output "endpoint" {
  description = "value of the EKS endpoint"
  value       = aws_eks_cluster.eks.endpoint
}