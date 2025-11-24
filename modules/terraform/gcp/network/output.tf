output "vpc_id" {
  description = "Vpc information"
  value       = google_compute_network.vpc.id

}

output "subnets" {
  description = "Map of subnet names to subnet objects"
  value       = { for subnet in google_compute_subnetwork.subnets : subnet.name => subnet.id }
}