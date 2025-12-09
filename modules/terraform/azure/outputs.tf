output "jumpbox_connection_info" {
  description = "Map of AKS role to jumpbox connection details"
  value = {
    for role, jumpbox in module.jumpbox :
    role => jumpbox.connection_info
  }
}
