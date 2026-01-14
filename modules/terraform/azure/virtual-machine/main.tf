locals {
  # Role assignments for AKS integration
  vm_role_assignments = (var.vm_config.aks_name != null && var.vm_config.aks_name != "") ? {
    "Azure Kubernetes Service Cluster User Role" = data.azurerm_kubernetes_cluster.aks[0].id
    "Reader"                                     = data.azurerm_resource_group.rg.id
  } : {}

  # Tags - merge global tags with VM-specific tags
  merged_tags = merge(var.tags, var.vm_config.vm_tags)

  # Get NIC ID from map
  nic_id = try(var.nics_map[var.vm_config.nic_name], null)
}


# =============================================================================
# Network Security Group (conditionally created)
# =============================================================================
resource "azurerm_network_security_group" "vm" {
  count               = var.vm_config.nsg.enabled ? 1 : 0
  name                = "${var.vm_config.name}-nsg"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = local.merged_tags

  dynamic "security_rule" {
    for_each = var.vm_config.nsg.rules
    content {
      name                       = security_rule.value.name
      priority                   = security_rule.value.priority
      direction                  = security_rule.value.direction
      access                     = security_rule.value.access
      protocol                   = security_rule.value.protocol
      source_port_range          = security_rule.value.source_port_range
      destination_port_range     = security_rule.value.destination_port_range
      source_address_prefix      = security_rule.value.source_address_prefix
      destination_address_prefix = security_rule.value.destination_address_prefix
    }
  }
}

# Associate the NSG with the NIC (if NSG is enabled)
resource "azurerm_network_interface_security_group_association" "vm" {
  count                     = var.vm_config.nsg.enabled ? 1 : 0
  network_interface_id      = local.nic_id
  network_security_group_id = azurerm_network_security_group.vm[0].id
}

# =============================================================================
# Linux Virtual Machine
# =============================================================================
resource "azurerm_linux_virtual_machine" "vm" {
  name                            = var.vm_config.name
  location                        = var.location
  resource_group_name             = var.resource_group_name
  size                            = var.vm_config.vm_size
  admin_username                  = var.vm_config.admin_username
  network_interface_ids           = [local.nic_id]
  disable_password_authentication = true
  custom_data                     = base64encode(templatefile("${path.module}/templates/${var.vm_config.cloud_init_template}", {}))
  tags                            = local.merged_tags

  admin_ssh_key {
    username   = var.vm_config.admin_username
    public_key = var.ssh_public_key
  }

  os_disk {
    caching              = var.vm_config.os_disk.caching
    storage_account_type = var.vm_config.os_disk.storage_account_type
    disk_size_gb         = var.vm_config.os_disk.disk_size_gb
  }

  source_image_reference {
    publisher = var.vm_config.image.publisher
    offer     = var.vm_config.image.offer
    sku       = var.vm_config.image.sku
    version   = var.vm_config.image.version
  }

  identity {
    type = "SystemAssigned"
  }
}

# =============================================================================
# Data Sources
# =============================================================================

# Get AKS cluster by name and resource group (optional)
data "azurerm_kubernetes_cluster" "aks" {
  count               = (var.vm_config.aks_name != null && var.vm_config.aks_name != "") ? 1 : 0
  name                = var.vm_config.aks_name
  resource_group_name = var.resource_group_name
}

# Get resource group for RBAC
data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

# =============================================================================
# Role Assignments (for AKS integration)
# =============================================================================
resource "azurerm_role_assignment" "vm_roles" {
  for_each             = local.vm_role_assignments
  scope                = each.value
  role_definition_name = each.key
  principal_id         = azurerm_linux_virtual_machine.vm.identity[0].principal_id
}
