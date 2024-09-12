output "endpoint" {
  description = "value of the EKS endpoint"
  value       = aws_eks_cluster.eks.endpoint
}

output "eks_cluster_data" {
  description = "value of the EKS kubeconfig"
  value       = aws_eks_cluster.eks
}