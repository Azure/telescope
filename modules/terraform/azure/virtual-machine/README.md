# Azure Virtual Machine Module

This module provisions virtual machines in Azure. It allows you to create and configure virtual machines with customizable settings.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the virtual machine will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the virtual machine will be deployed.
- **Type:** String
- **Default:** "eastus"

### `name`

- **Description:** Name of the virtual machine.
- **Type:** String
- **Default:** "client"

### `vm_sku`

- **Description:** SKU of the virtual machine.
- **Type:** String
- **Default:** "Standard_D2ds_v5"

### `nic`

- **Description:** ID of the network interface card (NIC) associated with the virtual machine.
- **Type:** String
- **Default:** ""

### `public_key`

- **Description:** Public key for SSH authentication.
- **Type:** String
- **Default:** ""

### `user_data_path`

- **Description:** Path to user data.
- **Type:** String
- **Default:** ""

### `vm_config`

- **Description:** Configuration for the virtual machine.
- **Type:** Object
  - `role`: Role of the virtual machine
  - `vm_name`: Name of the virtual machine
  - `nic_name`: Name of the network interface card
  - `admin_username`: Admin username for the virtual machine
  - `zone`: Availability zone for the virtual machine (optional)
  - `source_image_reference`: Reference to the source image for the virtual machine
  - `create_vm_extension`: Boolean value indicating whether to create a VM extension
- **Example:** Refer to your specific configuration

### `tags`

- **Type:** Map of strings
- **Default:** {}

### `ultra_ssd_enabled`

- **Description:** Indicates whether Ultra SSD is enabled for the virtual machine.
- **Type:** Boolean
- **Default:** false

## Usage Example

```hcl
module "virtual_machine" {
  source = "./virtual-machine"

  resource_group_name = "my-rg"
  location            = "West Europe"
  name                = "my-vm"
  vm_sku              = "Standard_D2s_v3"
  nic                 = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/networkInterfaces/my-nic"
  public_key          = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAB..."
  user_data_path      = "/path/to/user-data.sh"

  vm_config = {
    role           = "web"
    vm_name        = "web-vm"
    nic_name       = "web-nic"
    admin_username = "admin"
    zone           = 1
    source_image_reference = {
      publisher = "Canonical"
      offer     = "UbuntuServer"
      sku       = "16.04-LTS"
      version   = "latest"
    }
    create_vm_extension = true
  }

  tags = {
    environment = "production"
    project     = "example"
  }

  ultra_ssd_enabled = true
}
```
# Azure Virtual Machine Module Outputs

This module provides the following output:

## `vm`

- **Description:** Reference to the created virtual machine.
- **Type:** Object
- **Example:**
  ```hcl
  vm = {
    id   = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Compute/virtualMachines/my-vm"
    name = "my-vm"
    location = "East US"
    ...
  }
    ```