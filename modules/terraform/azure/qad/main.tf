locals {
  request_headers = [
    "Content-Type=application/json",
    "EnableQuickAttachDetach=true",
  ]

  cluster_url = format(
    "https://management.azure.com/subscriptions/%s/resourceGroups/%s/providers/Microsoft.ContainerService/managedClusters/%s?api-version=%s",
    data.azurerm_client_config.current.subscription_id,
    var.resource_group_name,
    var.qad_config.aks_name,
    var.qad_config.api_version,
  )

  system_node_pool = {
    name       = var.qad_config.system_node_pool.name
    count      = var.qad_config.system_node_pool.count
    vmSize     = var.qad_config.system_node_pool.vm_size
    osType     = var.qad_config.system_node_pool.os_type
    mode       = var.qad_config.system_node_pool.mode
    type       = var.qad_config.system_node_pool.vm_set_type
    nodeLabels = var.qad_config.system_node_pool.node_labels
  }

  user_node_pools = [
    for pool in var.qad_config.user_node_pools : {
      name       = pool.name
      count      = pool.count
      vmSize     = pool.vm_size
      osType     = pool.os_type
      mode       = pool.mode
      type       = pool.vm_set_type
      nodeLabels = pool.node_labels
    }
  ]

  network_profile = {
    for key, value in {
      networkPlugin = var.qad_config.network_profile.network_plugin
      podCidr       = var.qad_config.network_profile.pod_cidr
    } : key => value if value != null
  }

  body = {
    location = var.location
    tags = merge(
      var.tags,
      {
        role = var.qad_config.role
      },
    )
    identity = {
      type = var.qad_config.identity_type
    }
    sku = {
      name = var.qad_config.sku.name
      tier = var.qad_config.sku.tier
    }
    properties = {
      dnsPrefix         = var.qad_config.dns_prefix
      kubernetesVersion = var.qad_config.kubernetes_version
      oidcIssuerProfile = {
        enabled = true
      }
      storageProfile = {
        diskCSIDriver = {
          enabled = true
        }
      }
      agentPoolProfiles = concat([local.system_node_pool], local.user_node_pools)
      networkProfile    = local.network_profile
      servicePrincipalProfile = {
        clientId = "msi"
      }
    }
  }
}

data "azurerm_client_config" "current" {}

resource "terraform_data" "qad_cluster" {
  input = {
    body    = jsonencode(local.body)
    url     = local.cluster_url
    dry_run = var.qad_config.dry_run
  }

  provisioner "local-exec" {
    command = self.input.dry_run ? "echo \"$QAD_BODY\"" : <<-EOT
      set -euo pipefail
      az rest \
        --method put \
        --url "$QAD_URL" \
        --headers "Content-Type=application/json" "EnableQuickAttachDetach=true" \
        --body "$QAD_BODY" \
        --output none
    EOT

    environment = {
      QAD_BODY = self.input.body
      QAD_URL  = self.input.url
    }
    interpreter = ["/bin/bash", "-c"]
  }

  provisioner "local-exec" {
    when    = destroy
    command = self.input.dry_run ? "true" : <<-EOT
      set -euo pipefail
      status_code=$(az rest --method get --url "$QAD_URL" --output none 2>&1 || true)
      if [[ "$status_code" != *"ResourceNotFound"* ]]; then
        az rest --method delete --url "$QAD_URL" --output none
      fi
    EOT

    environment = {
      QAD_URL = self.input.url
    }
    interpreter = ["/bin/bash", "-c"]
  }
}
