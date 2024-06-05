output "aks_cluster_oidc_issuer" {
  description = "OIDC issuer for the AKS cluster"
  value       = azurerm_kubernetes_cluster.aks.oidc_issuer_url
}

output "aks_cluster_kubeconfig_path" {
  description = "Path to the kubeconfig file for the AKS cluster"
  value       = local_file.kube_config.filename
}