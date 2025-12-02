# Azure Jumpbox Module

This module provisions a Linux jumpbox virtual machine for accessing private AKS clusters. The jumpbox uses an externally created NIC (with public IP and NSG configured via tfvars), and supports automatic RBAC assignments for AKS access.

## Features

- **Managed Identity**: System-assigned managed identity for Azure authentication.
- **RBAC Integration**: Automatic role assignments for AKS cluster access.
- **Pre-installed Tools**: Configured via cloud-init (Docker, Azure CLI, kubectl, kubelogin, Helm).
- **SSH Access**: Configurable SSH public key.
- **External NIC**: Uses NIC created separately with public IP and NSG defined in tfvars.

## Architecture

The jumpbox module is designed to work with networking resources defined in your tfvars file:

1. **Public IP** - Created via `public_ip_config_list` in tfvars
2. **NSG (Network Security Group)** - Created via `network_config_list.network_security_group_name` with rules defined in `nsr_rules`
3. **NIC** - Created via `network_config_list.nic_public_ip_associations` and passed to jumpbox module via `nics_map`
4. **Jumpbox VM** - This module creates only the VM using the pre-configured NIC

## Input Variables

### `resource_group_name`
- **Description:** Resource group to deploy the jumpbox into.
- **Type:** `string`
- **Required:** Yes

### `location`
- **Description:** Azure region where the jumpbox will be deployed.
- **Type:** `string`
- **Required:** Yes

### `tags`
- **Description:** Tags applied to jumpbox resources. The module automatically appends `jumpbox=true`.
- **Type:** `map(string)`
- **Default:** `{}`

### `ssh_public_key`
- **Description:** SSH public key authorized on the jumpbox.
- **Type:** `string`
- **Sensitive:** Yes
- **Required:** Yes
- **Validation:** Must be a non-empty string.
- **Note:** In the pipeline, set `ssh_key_enabled: true` to automatically generate and provision this key.

### `jumpbox_config`
- **Description:** Configuration object for the jumpbox options.
- **Type:**
  ```hcl
  object({
    role     = string
    name     = string
    vm_size  = optional(string, "Standard_D4s_v3")
    nic_name = string
    aks_name = string
  })
  ```
- **Required:** Yes

### `nics_map`
- **Description:** Map of NIC names to their IDs. NICs are created externally via `network_config_list.nic_public_ip_associations` in tfvars.
- **Type:** `map(string)`
- **Required:** Yes

## Resources Created

- **azurerm_linux_virtual_machine**: The jumpbox VM (Ubuntu 24.04 LTS).
- **azurerm_role_assignment**: Grants the VM identity access to the AKS cluster and Resource Group.

## RBAC Role Assignments

When `jumpbox_config.aks_name` is valid, the module assigns:

1. **Azure Kubernetes Service Cluster User Role** on the AKS specific cluster (allows `az aks get-credentials`).
2. **Reader** on the Resource Group (allows discovery of the cluster via `az resource list`).

## Tfvars Configuration Example

The public IP, NSG, and NIC must be configured in your tfvars file. Here's a complete example:

```hcl
# 1. Create Public IP for jumpbox
public_ip_config_list = [
  {
    name  = "jumpbox-pip"
    count = 1
  }
]

# 2. Configure network with NSG and NIC
network_config_list = [
  {
    role               = "mycluster"
    vnet_name          = "my-vnet"
    vnet_address_space = "10.0.0.0/8"
    subnet = [
      {
        name           = "aks-subnet"
        address_prefix = "10.1.0.0/16"
      },
      {
        name           = "jumpbox-subnet"
        address_prefix = "10.2.0.0/16"
      }
    ]
    # NSG with SSH access rule
    network_security_group_name = "my-nsg"
    nsr_rules = [
      {
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
    ]
    # NIC with public IP association
    nic_public_ip_associations = [
      {
        nic_name              = "jumpbox-nic"
        subnet_name           = "jumpbox-subnet"
        ip_configuration_name = "primary"
        public_ip_name        = "jumpbox-pip"
        count                 = 1
      }
    ]
  }
]

# 3. Configure jumpbox VM
jumpbox_config_list = [
  {
    role     = "mycluster"
    name     = "my-jumpbox"
    vm_size  = "Standard_D4s_v3"
    nic_name = "jumpbox-nic"      # Must match nic_name in nic_public_ip_associations
    aks_name = "my-aks-cluster"
  }
]
```