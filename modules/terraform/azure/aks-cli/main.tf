locals {
  tags_list = [
    for key, value in merge(var.tags, { "role" = var.aks_cli_config.role }) :
    format("%s=%s", key, value)
  ]

  extra_pool_map = {
    for pool in var.aks_cli_config.extra_node_pool :
    pool.name => pool
  }

  aks_custom_headers_flags = (
    length(var.aks_cli_config.aks_custom_headers) == 0 ?
    "" :
    format(
      "%s %s",
      "--aks-custom-headers",
      join(",", var.aks_cli_config.aks_custom_headers),
    )
  )
}

resource "terraform_data" "aks_cli" {
  input = {
    group_name = var.resource_group_name,
    name       = var.aks_cli_config.aks_name
  }

  provisioner "local-exec" {
    command = join(" ", [
      "az",
      "aks",
      "create",
      "-g", self.input.group_name,
      "-n", self.input.name,
      "--location", var.location,
      "--tier", var.aks_cli_config.sku_tier,
      "--tags", join(" ", local.tags_list),
      local.aks_custom_headers_flags,
      "--no-ssh-key",
      "--enable-managed-identity",
      "--nodepool-name", var.aks_cli_config.default_node_pool.name,
      "--node-count", var.aks_cli_config.default_node_pool.node_count,
      "--node-vm-size", var.aks_cli_config.default_node_pool.vm_size,
    ])
  }

  provisioner "local-exec" {
    when = destroy
    command = join(" ", [
      "az",
      "aks",
      "delete",
      "-g", self.input.group_name,
      "-n", self.input.name,
      "--yes",
    ])
  }
}

resource "terraform_data" "aks_nodepool_cli" {
  depends_on = [
    terraform_data.aks_cli
  ]

  for_each = local.extra_pool_map

  provisioner "local-exec" {
    command = join(" ", [
      "az",
      "aks",
      "nodepool",
      "add",
      "-g", var.resource_group_name,
      "--cluster-name", var.aks_cli_config.aks_name,
      "--nodepool-name", each.value.name,
      "--node-count", each.value.node_count,
      "--node-vm-size", each.value.vm_size,
    ])
  }
}
