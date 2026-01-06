locals {
  admin_username = "azureuser"
  jumpbox_role_assignments = (var.jumpbox_config.aks_name != null && var.jumpbox_config.aks_name != "") ? {
    "Azure Kubernetes Service Cluster User Role" = data.azurerm_kubernetes_cluster.aks[0].id
    "Reader"                                     = data.azurerm_resource_group.rg.id
  } : {}

  public_ip_address_id = try(var.public_ips_map[var.jumpbox_config.public_ip_name].id, null)
  subnet_id            = try(var.subnets_map[var.jumpbox_config.subnet_name], null)
}


resource "azurerm_network_security_group" "jumpbox" {
  name                = "${var.jumpbox_config.name}-nsg"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = merge(var.tags, { "jumpbox" = "true" })

  security_rule {
    name                       = "AllowSSH"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_network_interface" "jumpbox" {
  name                = "${var.jumpbox_config.name}-nic"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = merge(var.tags, { "jumpbox" = "true" })

  ip_configuration {
    name                          = "primary"
    subnet_id                     = local.subnet_id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = local.public_ip_address_id
  }
}

# Associate the jumpbox network interface with the jumpbox network security group
resource "azurerm_network_interface_security_group_association" "jumpbox" {
  network_interface_id      = azurerm_network_interface.jumpbox.id
  network_security_group_id = azurerm_network_security_group.jumpbox.id
}

# Create the jumpbox virtual machine
resource "azurerm_linux_virtual_machine" "jumpbox" {
  name                            = var.jumpbox_config.name
  location                        = var.location
  resource_group_name             = var.resource_group_name
  size                            = var.jumpbox_config.vm_size
  admin_username                  = local.admin_username
  network_interface_ids           = [azurerm_network_interface.jumpbox.id]
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
