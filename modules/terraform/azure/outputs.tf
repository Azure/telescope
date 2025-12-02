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
