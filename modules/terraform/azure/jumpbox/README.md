# Azure Jumpbox Module

This module provisions a Linux jumpbox virtual machine for accessing private AKS clusters. The jumpbox creates its own NIC and NSG, and supports automatic RBAC assignments for AKS access.

## Features

- **Self-contained Networking**: Creates its own NIC and NSG with SSH access rule.
- **Managed Identity**: System-assigned managed identity for Azure authentication.
- **RBAC Integration**: Automatic role assignments for AKS cluster access.
- **Pre-installed Tools**: Configured via cloud-init (Docker, Azure CLI, kubectl, kubelogin, Helm).
- **SSH Access**: Configurable SSH public key.

## Resources Created

| Resource | Name Pattern | Description |
|----------|--------------|-------------|
| `azurerm_network_security_group` | `<name>-nsg` | NSG with SSH access rule |
| `azurerm_network_interface` | `<name>-nic` | NIC with dynamic private IP |
| `azurerm_network_interface_security_group_association` | - | Associates NIC with NSG |
| `azurerm_linux_virtual_machine` | `<name>` | Ubuntu 24.04 LTS VM |
| `azurerm_role_assignment` | - | RBAC roles for AKS access (if aks_name provided) |

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
- **Description:** Tags applied to jumpbox resources.
- **Type:** `map(string)`
- **Default:** `{}`

### `ssh_public_key`
- **Description:** SSH public key authorized on the jumpbox.
- **Type:** `string`
- **Sensitive:** Yes
- **Required:** Yes
- **Note:** In the pipeline, set `ssh_key_enabled: true` to automatically generate and provision this key.

### `jumpbox_config`
- **Description:** Jumpbox configuration object.
- **Type:**
  ```hcl
  object({
    role           = string
    name           = string
    vm_size        = optional(string, "Standard_D4s_v3")
    subnet_name    = string
    public_ip_name = string
    aks_name       = string
  })
  ```
- **Required:** Yes

| Field | Description |
|-------|-------------|
| `role` | Role identifier for the jumpbox (used for module mapping) |
| `name` | Name of the jumpbox VM |
| `vm_size` | Azure VM size (default: `Standard_D4s_v3`) |
| `subnet_name` | Name of the subnet to deploy the NIC into |
| `public_ip_name` | Name of the public IP to associate (from `public_ips_map`) |
| `aks_name` | Name of the AKS cluster for RBAC (optional, set to empty string to skip) |

### `public_ips_map`
- **Description:** Map of public IP names to their objects containing id and ip_address.
- **Type:** `map(object({ id = string, ip_address = string }))`
- **Required:** Yes

### `subnets_map`
- **Description:** Map of subnet names to subnet IDs.
- **Type:** `map(any)`
- **Default:** `{}`

## RBAC Assignments

When `aks_name` is provided, the following roles are automatically assigned to the jumpbox's managed identity:

| Role | Scope |
|------|-------|
| Azure Kubernetes Service Cluster User Role | AKS Cluster |
| Reader | Resource Group |

## Pre-installed Software (via cloud-init)

- Docker
- Azure CLI (with aks-preview extension)
- kubectl
- kubelogin (for AAD-enabled AKS)
- Helm
- Python 3 with pip and virtualenv
- Git, jq, curl, unzip

## Usage Example

### tfvars Configuration

```hcl
public_ip_config_list = [
  {
    name  = "jumpbox-pip"
    count = 1
  }
]

network_config_list = [
  {
    role               = "myapp"
    vnet_name          = "myapp-vnet"
    vnet_address_space = "10.0.0.0/16"
    subnet = [
      {
        name           = "aks-subnet"
        address_prefix = "10.0.0.0/20"
      },
      {
        name           = "jumpbox-subnet"
        address_prefix = "10.0.16.0/24"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]

jumpbox_config_list = [
  {
    role           = "myapp"
    name           = "myapp-jumpbox"
    vm_size        = "Standard_D4s_v3"
    subnet_name    = "jumpbox-subnet"
    public_ip_name = "jumpbox-pip"
    aks_name       = "myapp-aks"
  }
]
```
