resource "aws_placement_group" "placement-group" {
  name            = var.pg_name
  strategy        = var.pg_config.strategy
  tags            = var.tags
  partition_count = var.pg_config.partition_count
  spread_level    = var.pg_config.spread_level
}