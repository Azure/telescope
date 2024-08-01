This module provisions proximity placement groups in Azure 
## Input Variables


### `resource_group_name`

- **Description:** Name of the resource group where the proximity group will be created.
- **Type:** String
- **Default:** "rg"

### `location`

- **Description:** Azure region where the proximity group will be deployed.
- **Type:** String
- **Default:** "eastus"

### `name`

- **Description:** Name of the proximity group.
- **Type:** String
- **Default:** ""

### `tags`

- **Type:** Map of strings
- **Default:** {}

## Terraform Provider References

### Resources

- [azurerm_proximity_placement_group](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/proximity_placement_group)
