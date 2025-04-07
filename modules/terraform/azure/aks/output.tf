output "aks_cluster_oidc_issuer" {
  description = "OIDC issuer for the AKS cluster"
  value       = azurerm_kubernetes_cluster.aks.oidc_issuer_url
}

output "aks_cluster_kubeconfig_path" {
  description = "Path to the kubeconfig file for the AKS cluster"
  value       = local_file.save_kube_config.file_name
}

output "aks_cluster" {
  description = "Used for unit tests"
  value       = azurerm_kubernetes_cluster.aks
}

output "aks_cluster_nood_pools" {
  description = "Used for unit tests"
  value       = azurerm_kubernetes_cluster_node_pool.aks_node_pools
}
