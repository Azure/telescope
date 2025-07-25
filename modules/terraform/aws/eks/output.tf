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

# Auto Mode related outputs
output "automode_controller_policy" {
  description = "Auto Mode controller IAM policy. Used for unit tests"
  value       = var.eks_config.auto_mode && (var.eks_config.node_pool_system || var.eks_config.node_pool_general_purpose) ? aws_iam_policy.automode_controller_policy : []
}

output "automode_controller_policy_attachments" {
  description = "Auto Mode controller IAM policy attachments. Used for unit tests"
  value       = var.eks_config.auto_mode && (var.eks_config.node_pool_system || var.eks_config.node_pool_general_purpose) ? aws_iam_role_policy_attachment.automode_controller_policy_attachments : []
}

output "node_pool_entry" {
  description = "EKS access entry for Auto Mode node pools. Used for unit tests"
  value       = var.eks_config.auto_mode && (var.eks_config.node_pool_system || var.eks_config.node_pool_general_purpose) ? aws_eks_access_entry.node_pool_entry : []
}

output "node_pool_policy" {
  description = "EKS access policy association for Auto Mode node pools. Used for unit tests"
  value       = var.eks_config.auto_mode && (var.eks_config.node_pool_system || var.eks_config.node_pool_general_purpose) ? aws_eks_access_policy_association.node_pool_policy : []
}

output "apply_metrics_server_addon" {
  description = "Terraform data resource for metrics-server manifest application. Used for unit tests"
  value       = terraform_data.apply_metrics_server_addon
}