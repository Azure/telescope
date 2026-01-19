# Azure Virtual Machine Module

This module creates a configurable Linux virtual machine in Azure with support for custom NSG rules, OS disk configuration, VM images, and cloud-init templates. The NIC is created externally via the network module and passed in.

## Features

- **External NIC**: Uses NIC created by the network module (passed via `nics_map`)
- **Configurable NSG**: Enable/disable NSG and define custom security rules, associated with the external NIC
- **Custom OS Disk**: Configure caching, storage type, and disk size
- **Flexible Image Selection**: Use any Azure VM image (defaults to Ubuntu 24.04 LTS)
- **Cloud-init Templates**: Select from multiple cloud-init templates or provide custom variables
- **AKS Integration**: Optional role assignments for AKS cluster access
- **Tagging**: Global and VM-specific tags support

## Usage

### Basic Usage (Jumpbox-like VM)

```hcl
module "jumpbox" {
  source = "./modules/terraform/azure/virtual-machine"

  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  ssh_public_key      = var.ssh_public_key

  vm_config = {
    role     = "jumpbox"
    name     = "my-jumpbox"
    vm_size  = "Standard_D4s_v3"
    nic_name = "jumpbox-nic"  # NIC name from network module
    aks_name = "my-aks-cluster"

    nsg = {
      enabled = true
      rules = [
        {
          name                   = "AllowSSH"
          priority               = 100
          destination_port_range = "22"
        }
      ]
    }
    vm_tags = {
      jumpbox = "true"
    }
  }

  nics_map = module.virtual_network["main"].nics
  tags     = var.tags
}
```

### Advanced Usage (Custom Configuration)

```hcl
module "custom_vm" {
  source = "./modules/terraform/azure/virtual-machine"

  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  ssh_public_key      = var.ssh_public_key

  vm_config = {
    role           = "worker"
    name           = "my-worker-vm"
    vm_size        = "Standard_D8s_v3"
    admin_username = "adminuser"
    nic_name       = "worker-nic"

    os_disk = {
      caching              = "ReadWrite"
      storage_account_type = "Premium_LRS"
      disk_size_gb         = 256
    }

    image = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts-gen2"
      version   = "latest"
    }

    nsg = {
      enabled = true
      rules = [
        {
          name                   = "AllowSSH"
          priority               = 100
          destination_port_range = "22"
        },
        {
          name                   = "AllowHTTPS"
          priority               = 110
          destination_port_range = "443"
        }
      ]
    }

    cloud_init = {
      template_file = "cloud-init.tpl"
      vars          = {}
    }
  }

  nics_map = module.virtual_network["main"].nics
  tags     = var.tags
}
```

### VM without NSG

```hcl
module "vm_no_nsg" {
  source = "./modules/terraform/azure/virtual-machine"

  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  ssh_public_key      = var.ssh_public_key

  vm_config = {
    role     = "internal"
    name     = "internal-vm"
    nic_name = "internal-nic"
    
    nsg = {
      enabled = false
    }
  }

  nics_map = module.virtual_network["main"].nics
}
```

## Variables

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| resource_group_name | Resource group to deploy the virtual machine into | `string` | n/a | yes |
| location | Azure region | `string` | n/a | yes |
| ssh_public_key | SSH public key authorized on the virtual machine | `string` | n/a | yes |
| vm_config | Virtual machine configuration object | `object` | n/a | yes |
| nics_map | Map of NIC names to NIC IDs (from network module) | `map(string)` | `{}` | no |
| tags | Tags applied to all virtual machine resources | `map(string)` | `{}` | no |

### vm_config Object

| Attribute | Description | Type | Default |
|-----------|-------------|------|---------|
| role | Role identifier for the VM | `string` | required |
| name | Name of the virtual machine | `string` | required |
| vm_size | Azure VM size | `string` | `"Standard_D4s_v3"` |
| admin_username | Admin username for SSH | `string` | `"azureuser"` |
| nic_name | Name of the NIC from nics_map | `string` | required |
| aks_name | AKS cluster name for role assignments | `string` | `null` |
| os_disk | OS disk configuration | `object` | See below |
| image | VM image configuration | `object` | See below |
| nsg | NSG configuration | `object` | See below |
| cloud_init_template | Cloud-init template file name in templates/ folder | `string` | `"cloud-init.tpl"` |
| vm_tags | VM-specific tags (merged with global tags) | `map(string)` | `{}` |

### os_disk Object

| Attribute | Description | Default |
|-----------|-------------|---------|
| caching | OS disk caching mode | `"ReadWrite"` |
| storage_account_type | Storage account type | `"Standard_LRS"` |
| disk_size_gb | OS disk size in GB | `64` |

### image Object

| Attribute | Description | Default |
|-----------|-------------|---------|
| publisher | Image publisher | `"Canonical"` |
| offer | Image offer | `"ubuntu-24_04-lts"` |
| sku | Image SKU | `"server"` |
| version | Image version | `"latest"` |

### nsg Object

| Attribute | Description | Default |
|-----------|-------------|---------|
| enabled | Whether to create NSG and associate with NIC | `false` |
| rules | List of security rules | `[]` |

## Outputs

This module currently does not define any Terraform outputs.

To expose values (such as VM identifiers or NSG IDs) to module consumers, add the appropriate `output` blocks in an `outputs.tf` file within this module.
## Templates

Place your cloud-init templates in the `templates/` folder. The default template is `cloud-init.tpl`.

### Using Custom Templates

Reference a custom template file:
```hcl
cloud_init_template = "custom-init.tpl"
```