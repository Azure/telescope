resource "aws_placement_group" "placement-group" {
  name            = var.pg_name
  strategy        = var.placement_group_config.strategy
  tags            = var.tags
  partition_count = var.placement_group_config.partition_count
  spread_level    = var.placement_group_config.spread_level
}