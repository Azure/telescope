output "aks_cluster_fqdn" {
  description = "FQDN of the created AKS cluster"
  value       = azapi_resource.this.output.properties.fqdn
}

output "resource_name" {
  description = "The name of the created AKS cluster"
  value       = azapi_resource.this.name
}

output "resource_body" {
  description = "The request body of the AzAPI resource"
  value       = local.body
}

output "resource_output" {
  description = "The full output from the AzAPI resource"
  value       = azapi_resource.this.output
}
