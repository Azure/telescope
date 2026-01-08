locals {
  admin_username = "azureuser"
  jumpbox_role_assignments = (var.jumpbox_config.aks_name != null && var.jumpbox_config.aks_name != "") ? {
    "Azure Kubernetes Service Cluster User Role" = data.azurerm_kubernetes_cluster.aks[0].id
    "Reader"                                     = data.azurerm_resource_group.rg.id
  } : {}

  public_ip_address_id = try(var.public_ips_map[var.jumpbox_config.public_ip_name].id, null)
  subnet_id            = try(var.subnets_map[var.jumpbox_config.subnet_name], null)

  # ============================================================================
  # Standard configuration for jumpbox VMs
  # These are the default values used for all jumpbox instances.
  # Modify these values if you need to customize the jumpbox configuration.
  # ============================================================================

  # OS disk configuration
  os_disk_caching              = "ReadWrite"
  os_disk_storage_account_type = "Standard_LRS"
  os_disk_size_gb              = 128

  # VM image configuration (Ubuntu 24.04 LTS)
  image_publisher = "Canonical"
  image_offer     = "ubuntu-24_04-lts"
  image_sku       = "server"
  image_version   = "latest"

  # VM identity type - SystemAssigned for RBAC role assignments
  identity_type = "SystemAssigned"

  # NSG security rule configuration
  # Open SSH port 22 for remote access to the jumpbox
  ssh_rule_name                       = "AllowSSH"
  ssh_rule_priority                   = 100
  ssh_rule_direction                  = "Inbound"
  ssh_rule_access                     = "Allow"
  ssh_rule_protocol                   = "Tcp"
  ssh_rule_source_port_range          = "*"
  ssh_rule_destination_port_range     = "22"
  ssh_rule_source_address_prefix      = "*"
  ssh_rule_destination_address_prefix = "*"
}


resource "azurerm_network_security_group" "jumpbox" {
  name                = "${var.jumpbox_config.name}-nsg"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = merge(var.tags, { "jumpbox" = "true" })

  security_rule {
    name                       = local.ssh_rule_name
    priority                   = local.ssh_rule_priority
    direction                  = local.ssh_rule_direction
    access                     = local.ssh_rule_access
    protocol                   = local.ssh_rule_protocol
    source_port_range          = local.ssh_rule_source_port_range
    destination_port_range     = local.ssh_rule_destination_port_range
    source_address_prefix      = local.ssh_rule_source_address_prefix
    destination_address_prefix = local.ssh_rule_destination_address_prefix
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
    caching              = local.os_disk_caching
    storage_account_type = local.os_disk_storage_account_type
    disk_size_gb         = local.os_disk_size_gb
  }

  source_image_reference {
    publisher = local.image_publisher
    offer     = local.image_offer
    sku       = local.image_sku
    version   = local.image_version
  }

  identity {
    type = local.identity_type
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