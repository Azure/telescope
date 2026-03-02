output "aks_cluster_fqdn" {
  description = "FQDN of the created AKS cluster"
  value       = azapi_resource.this.output.properties.fqdn
}

output "resource_id" {
  description = "The ID of the created AKS cluster"
  value       = azapi_resource.this.id
}

output "resource_output" {
  description = "The full output from the AzAPI resource"
  value       = azapi_resource.this.output
}
