locals {
  minimum_aks_preview_version = "22.0.0b13"
  tags                        = merge(var.tags, { role = var.qad_config.role })
  tag_arguments               = join(" ", [for key, value in local.tags : format("%s=%s", key, value)])
  system_node_labels          = join(" ", [for key, value in var.qad_config.system_node_pool.node_labels : format("%s=%s", key, value)])

  create_arguments = compact([
    "az aks create",
    format("--resource-group %s", var.resource_group_name),
    format("--name %s", var.qad_config.aks_name),
    format("--location %s", var.location),
    format("--dns-name-prefix %s", var.qad_config.dns_prefix),
    format("--kubernetes-version %s", var.qad_config.kubernetes_version),
    format("--tier %s", var.qad_config.sku_tier),
    format("--nodepool-name %s", var.qad_config.system_node_pool.name),
    format("--node-count %d", var.qad_config.system_node_pool.count),
    format("--node-vm-size %s", var.qad_config.system_node_pool.vm_size),
    format("--node-osdisk-type %s", var.qad_config.system_node_pool.os_disk_type),
    format("--vm-set-type %s", var.qad_config.system_node_pool.vm_set_type),
    length(var.qad_config.system_node_pool.node_labels) > 0 ? format("--nodepool-labels %s", local.system_node_labels) : "",
    format("--network-plugin %s", var.qad_config.network_profile.network_plugin),
    var.qad_config.network_profile.pod_cidr != null ? format("--pod-cidr %s", var.qad_config.network_profile.pod_cidr) : "",
    "--generate-ssh-keys",
    "--aks-custom-headers EnableQuickAttachDetach=true",
    "--enable-disk-driver",
    "--enable-oidc-issuer",
  ])
  create_command = join(" ", concat(
    local.create_arguments,
    [format("--tags %s", local.tag_arguments)],
  ))

  delete_command = join(" ", [
    "az aks delete",
    format("--resource-group %s", var.resource_group_name),
    format("--name %s", var.qad_config.aks_name),
    "--yes",
  ])

  user_node_pool_map = { for pool in var.qad_config.user_node_pools : pool.name => pool }
  node_pool_commands = {
    for name, pool in local.user_node_pool_map : name => join(" ", compact([
      "az aks nodepool add",
      format("--resource-group %s", var.resource_group_name),
      format("--cluster-name %s", var.qad_config.aks_name),
      format("--name %s", pool.name),
      format("--node-count %d", pool.count),
      format("--node-vm-size %s", pool.vm_size),
      format("--node-osdisk-type %s", pool.os_disk_type),
      format("--os-type %s", pool.os_type),
      format("--mode %s", pool.mode),
      format("--vm-set-type %s", pool.vm_set_type),
      length(pool.node_labels) > 0 ? format(
        "--labels %s",
        join(" ", [for key, value in pool.node_labels : format("%s=%s", key, value)]),
      ) : "",
      "--aks-custom-headers EnableQuickAttachDetach=true",
    ]))
  }
}

resource "terraform_data" "aks_preview_extension" {
  input = {
    minimum_version = local.minimum_aks_preview_version
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -euo pipefail
      if ! az extension show --name aks-preview --output none 2>/dev/null; then
        az extension add --name aks-preview --yes
      fi
      az extension update --name aks-preview

      installed_version=$(az extension show --name aks-preview --query version --output tsv)
      minimum_version="$MINIMUM_VERSION"
      normalize_version() {
        if [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
          printf '%sz\n' "$1"
        else
          printf '%s\n' "$1"
        fi
      }
      normalized_minimum=$(normalize_version "$minimum_version")
      normalized_installed=$(normalize_version "$installed_version")
      oldest_version=$(printf '%s\n%s\n' "$normalized_minimum" "$normalized_installed" | sort -V | head -n1)
      if [[ "$oldest_version" != "$normalized_minimum" ]]; then
        echo "aks-preview $installed_version is installed; version $minimum_version or newer is required." >&2
        exit 1
      fi
      echo "aks-preview $installed_version satisfies the minimum version $minimum_version."
    EOT

    environment = {
      MINIMUM_VERSION = self.input.minimum_version
    }
    interpreter = ["/bin/bash", "-c"]
  }
}

resource "terraform_data" "qad_cluster" {
  depends_on = [terraform_data.aks_preview_extension]

  input = {
    create_command = var.qad_config.dry_run ? "echo '${local.create_command}'" : local.create_command
    delete_command = var.qad_config.dry_run ? "true" : local.delete_command
  }

  provisioner "local-exec" {
    command     = self.input.create_command
    interpreter = ["/bin/bash", "-c"]
  }

  provisioner "local-exec" {
    when        = destroy
    command     = self.input.delete_command
    interpreter = ["/bin/bash", "-c"]
  }
}

resource "terraform_data" "qad_node_pool" {
  for_each = local.node_pool_commands

  depends_on = [terraform_data.qad_cluster]

  input = {
    create_command = var.qad_config.dry_run ? "echo '${each.value}'" : each.value
  }

  provisioner "local-exec" {
    command     = self.input.create_command
    interpreter = ["/bin/bash", "-c"]
  }
}
