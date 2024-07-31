This module provisions proximity placement groups in AWS 
## Input Variables

### `resource_group_name`

- **Description:** Name of the resource group where the proximity group will be created.
- **Type:** String
- **Default:** "rg"

### `strategy`

- **Description:**  Required placement strategy. Can be cluster, partition, or spread 
- **Type:** String
- **Default:** "partition"

### `name`

- **Description:** Name of the proximity group. Will be set as Run ID . Need to be unique per account 
- **Type:** String
- **Default:** ""

### `tags`

- **Type:** Map of strings
- **Default:** {}


## Terraform Provider References

### Resources

- [aws_placement_group](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/placement_group)
