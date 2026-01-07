locals {
  admin_username = "azureuser"
  jumpbox_role_assignments = (var.jumpbox_config.aks_name != null && var.jumpbox_config.aks_name != "") ? {
    "Azure Kubernetes Service Cluster User Role" = data.azurerm_kubernetes_cluster.aks[0].id
    "Reader"                                     = data.azurerm_resource_group.rg.id
  } : {}
  nic = var.nics_map[var.jumpbox_config.nic_name]
}

# Create the jumpbox virtual machine
resource "azurerm_linux_virtual_machine" "jumpbox" {
  name                            = var.jumpbox_config.name
  location                        = var.location
  resource_group_name             = var.resource_group_name
  size                            = var.jumpbox_config.vm_size
  admin_username                  = local.admin_username
  network_interface_ids           = [local.nic]
  disable_password_authentication = true
  custom_data                     = base64encode(templatefile("${path.module}/templates/cloud-init.tpl", {}))
  tags                            = merge(var.tags, { "jumpbox" = "true" })

  admin_ssh_key {
    username   = local.admin_username
    public_key = var.ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = 128
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  identity {
    type = "SystemAssigned"
  }
}

# Get AKS cluster by name and resource group
data "azurerm_kubernetes_cluster" "aks" {
  count               = (var.jumpbox_config.aks_name != null && var.jumpbox_config.aks_name != "") ? 1 : 0
  name                = var.jumpbox_config.aks_name
  resource_group_name = var.resource_group_name
}

# Get resource group for RBAC
data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

resource "azurerm_role_assignment" "jumpbox_roles" {
  for_each             = local.jumpbox_role_assignments
  scope                = each.value
  role_definition_name = each.key
  principal_id         = azurerm_linux_virtual_machine.jumpbox.identity[0].principal_id
}
