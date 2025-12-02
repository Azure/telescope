locals {
  admin_username = "azureuser"
  ssh_rules = [
    for idx, cidr in ["0.0.0.0/0"] : {
      name     = format("AllowSSH-%03d", idx + 1)
      cidr     = cidr
      priority = 100 + idx * 10
    }
  ]
}

resource "azurerm_public_ip" "jumpbox" {
  name                = "${var.name}-pip"
  location            = var.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}


resource "azurerm_network_security_group" "jumpbox" {
  name                = "${var.name}-nsg"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  dynamic "security_rule" {
    for_each = { for rule in local.ssh_rules : rule.name => rule }
    content {
      name                       = security_rule.value.name
      priority                   = security_rule.value.priority
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "22"
      source_address_prefix      = security_rule.value.cidr
      destination_address_prefix = "*"
    }
  }
}

resource "azurerm_network_interface" "jumpbox" {
  name                = "${var.name}-nic"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  ip_configuration {
    name                          = "primary"
    subnet_id                     = var.subnet_id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.jumpbox.id
  }
}

resource "azurerm_network_interface_security_group_association" "jumpbox" {
  network_interface_id      = azurerm_network_interface.jumpbox.id
  network_security_group_id = azurerm_network_security_group.jumpbox.id
}


resource "azurerm_linux_virtual_machine" "jumpbox" {
  name                            = var.name
  location                        = var.location
  resource_group_name             = var.resource_group_name
  size                            = var.vm_size
  admin_username                  = local.admin_username
  network_interface_ids           = [azurerm_network_interface.jumpbox.id]
  disable_password_authentication = true
  custom_data                     = base64encode(templatefile("${path.module}/templates/cloud-init.tpl", {}))
  tags                            = var.tags

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

# Get current subscription for RBAC scope

# Get AKS cluster by name and resource group
data "azurerm_kubernetes_cluster" "aks" {
  count               = var.aks_cluster_name != null ? 1 : 0
  name                = var.aks_cluster_name
  resource_group_name = var.resource_group_name
}

# RBAC: Azure Kubernetes Service Cluster User Role - allows az aks get-credentials
resource "azurerm_role_assignment" "jumpbox_aks_cluster_user" {
  count                = var.aks_cluster_name != null ? 1 : 0
  scope                = data.azurerm_kubernetes_cluster.aks[0].id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = azurerm_linux_virtual_machine.jumpbox.identity[0].principal_id
}

# RBAC: Azure Kubernetes Service RBAC Cluster Admin - allows kubectl operations
resource "azurerm_role_assignment" "jumpbox_aks_rbac_admin" {
  count                = var.aks_cluster_name != null ? 1 : 0
  scope                = data.azurerm_kubernetes_cluster.aks[0].id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = azurerm_linux_virtual_machine.jumpbox.identity[0].principal_id
}

# Get resource group for RBAC
data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

# RBAC: Reader role on resource group - allows az resource list
resource "azurerm_role_assignment" "jumpbox_rg_reader" {
  scope                = data.azurerm_resource_group.rg.id
  role_definition_name = "Reader"
  principal_id         = azurerm_linux_virtual_machine.jumpbox.identity[0].principal_id
}

