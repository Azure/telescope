output "jumpbox_connection_info" {
  description = "Map of AKS role to jumpbox connection details"
  value = {
    for role, jumpbox in module.jumpbox :
    role => {
      public_ip  = jumpbox.public_ip
      private_ip = jumpbox.private_ip
      username   = jumpbox.admin_username
      name       = jumpbox.name
    }
  }
}

output "aks_kubeconfig_paths" {
  description = "Local kubeconfig paths generated for each AKS role"
  value = {
    for role, aks in module.aks :
    role => aks.aks_cluster_kubeconfig_path
  }
}
