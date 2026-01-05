# Azure Jumpbox Module

This module provisions a Linux jumpbox virtual machine for accessing private AKS clusters. It supports configuration via a structured object, integration with existing subnets and public IPs, and automatic RBAC assignments.

## Features

- **Managed Identity**: System-assigned managed identity for Azure authentication.
- **RBAC Integration**: Automatic role assignments for AKS cluster access.
- **Pre-installed Tools**: Configured via cloud-init (Docker, Azure CLI, kubectl, kubelogin, Helm).
- **SSH Access**: Configurable SSH public key.
- **Networking**: flexible subnet and public IP association.

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

### `jumpbox_config`
- **Description:** Configuration object for the jumpbox options.
- **Type:**
  ```hcl
  object({
    name           = string
    subnet_name    = string
    vm_size        = optional(string, "Standard_D4s_v3")
    public_ip_name = optional(string, null)
    aks_name       = string
  })
  ```
- **Required:** Yes

### `public_ips_map`
- **Description:** Map of public IP names to their objects (containing `id` and `ip_address`). Used to resolve `public_ip_name` from `jumpbox_config`.
- **Type:**
  ```hcl
  map(object({
    id         = string
    ip_address = string
  }))
  ```
- **Required:** Yes

### `subnets_map`
- **Description:** Map of subnet names to subnet ids. Used to resolve `subnet_name` from `jumpbox_config`.
- **Type:** `map(any)`
- **Default:** `{}`

## Resources Created

- **azurerm_linux_virtual_machine**: The jumpbox VM ("Ubuntu 24.04 LTS").
- **azurerm_network_interface**: NIC for the VM.
- **azurerm_network_security_group**: NSG allowing inbound SSH (port 22).
- **azurerm_role_assignment**: Grants the VM identity access to the AKS cluster and Resource Group.

## RBAC Role Assignments

When `jumpbox_config.aks_name` is valid, the module assigns:

1.  **Azure Kubernetes Service Cluster User Role** on the AKS specific cluster (allows `az aks get-credentials`).
2.  **Reader** on the Resource Group (allows discovery of the cluster via `az resource list`).

## Usage Example

```hcl
module "jumpbox" {
  source = "./modules/terraform/azure/jumpbox"

  resource_group_name = azurerm_resource_group.rg.name
  location            = "eastus"
  ssh_public_key      = var.ssh_public_key
  
  jumpbox_config = {
    name           = "my-jumpbox"
    subnet_name    = "default"
    vm_size        = "Standard_D4s_v3"
    public_ip_name = "jumpbox-pip"
    aks_name       = "my-aks-cluster"
  }

  public_ips_map = {
    "jumpbox-pip" = {
        id = "/subscriptions/.../publicIPAddresses/jumpbox-pip"
        ip_address = "20.x.x.x"
    }
  }
  
  subnets_map = {
    "default" = "/subscriptions/.../subnets/default"
  }

  tags = {
    Environment = "Dev"
  }
}
```
