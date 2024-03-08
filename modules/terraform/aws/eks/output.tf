output "endpoint" {
  description = "value of the EKS endpoint"
  value       = aws_eks_cluster.eks.endpoint
}

output "kubeconfig-certificate-authority-data" {
  description = "value of the EKS certificate authority data"
  value       = aws_eks_cluster.eks.certificate_authority[0].data
}