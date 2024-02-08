locals {
  publisher = var.vm_config.source_image_reference.publisher
  offer     = var.vm_config.source_image_reference.offer
  sku       = var.vm_config.source_image_reference.sku
  version   = var.vm_config.source_image_reference.version
}

resource "azurerm_linux_virtual_machine" "vm" {
  name                  = var.name
  resource_group_name   = var.resource_group_name
  location              = var.location
  size                  = var.vm_sku
  network_interface_ids = [var.nic]

  admin_username = var.vm_config.admin_username
  admin_ssh_key {
    username   = var.vm_config.admin_username
    public_key = var.public_key
  }
  disable_password_authentication = true

  source_image_reference {
    publisher = local.publisher
    offer     = local.offer
    sku       = local.sku
    version   = local.version
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }
  tags = merge(
    var.tags,
    {
      "role" = var.vm_config.role
    },
  )

  zone = var.vm_config.zone

  additional_capabilities {
    ultra_ssd_enabled = var.ultra_ssd_enabled
  }
}

resource "azurerm_virtual_machine_extension" "vm_ext" {
  count                = var.vm_config.create_vm_extension ? 1 : 0
  name                 = "${var.vm_config.role}-vm-ext"
  virtual_machine_id   = azurerm_linux_virtual_machine.vm.id
  publisher            = "Microsoft.Azure.Extensions"
  type                 = "CustomScript"
  type_handler_version = "2.0"
  protected_settings   = <<PROT
  {
    "script" : "${base64encode(file("${var.user_data_path}/${var.vm_config.role}-userdata.sh"))}"
  }
PROT
  depends_on           = [azurerm_linux_virtual_machine.vm]
}
