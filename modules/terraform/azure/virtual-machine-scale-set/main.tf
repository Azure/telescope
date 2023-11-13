locals {
  publisher = var.vmss_config.source_image_reference.publisher
  offer     = var.vmss_config.source_image_reference.offer
  sku       = var.vmss_config.source_image_reference.sku
  version   = var.vmss_config.source_image_reference.version
}

resource "azurerm_linux_virtual_machine_scale_set" "vmss" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.vm_sku
  instances           = var.vmss_config.number_of_instances

  admin_username = var.vmss_config.admin_username
  admin_ssh_key {
    username   = var.vmss_config.admin_username
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

  network_interface {
    name                          = "${var.name}-nic"
    primary                       = true
    enable_accelerated_networking = true

    ip_configuration {
      name                                   = var.ip_configuration_name
      primary                                = true
      subnet_id                              = var.subnet_id
      load_balancer_backend_address_pool_ids = [var.lb_pool_id]
    }
  }

  upgrade_mode = "Automatic"

  tags = var.tags
}

resource "azurerm_virtual_machine_scale_set_extension" "vmss_ext" {
  count                        = var.user_data_path != "" ? 1 : 0
  name                         = "${var.vmss_config.name_prefix}-vmss-ext"
  virtual_machine_scale_set_id = azurerm_linux_virtual_machine_scale_set.vmss.id
  publisher                    = "Microsoft.Azure.Extensions"
  type                         = "CustomScript"
  type_handler_version         = "2.0"
  settings = jsonencode({
    "script" = base64encode(file("${var.user_data_path}/${var.vmss_config.name_prefix}-userdata.sh"))
  })
  depends_on = [azurerm_linux_virtual_machine_scale_set.vmss]
}
