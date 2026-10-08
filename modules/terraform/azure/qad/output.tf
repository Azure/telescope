output "cluster_name" {
  description = "Name of the QAD-enabled AKS cluster"
  value       = var.qad_config.aks_name
}

output "request_body" {
  description = "ARM request body used to create the QAD-enabled AKS cluster"
  value       = local.body
}

output "request_url" {
  description = "ARM request URL used to create the QAD-enabled AKS cluster"
  value       = local.cluster_url
}

output "request_headers" {
  description = "HTTP headers used to enable Quick Attach/Detach"
  value       = local.request_headers
}
