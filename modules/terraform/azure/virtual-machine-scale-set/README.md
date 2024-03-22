# Azure Virtual Machine Scale Set (VMSS) Module

This module provisions virtual machine scale sets in Azure. It allows you to create and manage a group of identical, load balanced virtual machines.

## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the VMSS will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the VMSS will be deployed.
- **Type:** String
- **Default:** "eastus"

### `name`

- **Description:** Name of the virtual machine scale set.
- **Type:** String
- **Default:** "client-vmss"

### `vm_sku`

- **Description:** SKU of the virtual machines in the scale set.
- **Type:** String
- **Default:** "Standard_D2ds_v5"

### `public_key`

- **Description:** Public key for SSH authentication.
- **Type:** String
- **Default:** ""

### `subnet_id`

- **Description:** ID of the subnet where the VMSS instances will be placed.
- **Type:** String
- **Default:** ""

### `ip_configuration_name`

- **Description:** Name of the IP configuration for the VMSS instances.
- **Type:** String
- **Default:** ""

### `lb_pool_id`

- **Description:** ID of the load balancer pool associated with the VMSS instances.
- **Type:** String
- **Default:** ""

### `tags`

- **Type:** Map of strings
- **Default:** {}

### `user_data_path`

- **Description:** Path to user data.
- **Type:** String
- **Default:** ""

### `vmss_config`

- **Description:** Configuration for the virtual machine scale set.
- **Type:** Object
  - `role`: Role of the virtual machine scale set
  - `vmss_name`: Name of the virtual machine scale set
  - `admin_username`: Admin username for the VMSS instances
  - `nic_name`: Name of the network interface card
  - `subnet_name`: Name of the subnet
  - `loadbalancer_pool_name`: Name of the load balancer pool
  - `ip_configuration_name`: Name of the IP configuration
  - `number_of_instances`: Number of instances in the scale set
  - `source_image_reference`: Reference to the source image for the VMSS instances
- **Example:** Refer to your specific configuration

## Usage Example

```hcl
module "vmss" {
  source = "./vmss"

  resource_group_name = "my-rg"
  location            = "West Europe"
  name                = "my-vmss"
  vm_sku              = "Standard_D2s_v3"
  public_key          = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAB..."
  subnet_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/virtualNetworks/my-vnet/subnets/my-subnet"
  ip_configuration_name = "ipconfig1"
  lb_pool_id          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Network/loadBalancers/my-lb/backendAddressPools/my-pool"

  vmss_config = {
    role                   = "web"
    vmss_name              = "web-vmss"
    admin_username         = "admin"
    nic_name               = "web-nic"
    subnet_name            = "web-subnet"
    loadbalancer_pool_name = "web-pool"
    ip_configuration_name  = "web-ipconfig"
    number_of_instances    = 3
    source_image_reference = {
      publisher = "Canonical"
      offer     = "UbuntuServer"
      sku       = "16.04-LTS"
      version   = "latest"
    }
  }

  tags = {
    environment = "production"
    project     = "example"
  }
}
```
