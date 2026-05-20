locals {
  tags_list = [
    for key, value in merge(var.tags, { "role" = var.aks_cli_config.role }) :
    format("%s=%s", key, value)
  ]

  acr_pull_scopes_for_each = (!var.aks_cli_config.dry_run && var.enable_kubelet_identity) ? var.acr_pull_scopes_map : {}

  extra_pool_map = {
    for pool in var.aks_cli_config.extra_node_pool :
    pool.name => pool
  }

  # Pre-built `az aks nodepool add` command per extra pool. Pulled into a
  # local so the terraform_data.aks_nodepool_cli heredoc body stays readable
  # (avoids a multi-line interpolation inside the bash retry-loop heredoc,
  # which `terraform fmt` otherwise mangles).
  extra_pool_commands = {
    for pool in var.aks_cli_config.extra_node_pool : pool.name => join(" ", [
      "az",
      "aks",
      "nodepool",
      "add",
      "-g", var.resource_group_name,
      "--cluster-name", var.aks_cli_config.aks_name,
      "--nodepool-name", pool.name,
      "--node-count", pool.node_count,
      "--node-vm-size", pool.vm_size,
      "--vm-set-type", pool.vm_set_type,
      "--node-osdisk-type", pool.os_disk_type,
      local.aks_custom_headers_flags,
      # If the default pool uses --pod-subnet-id (Azure CNI dynamic IP
      # allocation), AKS requires ALL agent pools to set it (or none).
      # Without this, `az aks nodepool add` on extra pools fails with
      # `InvalidParameter: All or none of the agentpools should set
      # podsubnet`. Reuse the same pod subnet as the default pool — extra
      # pools (e.g. prompool) host non-workload pods so the per-pool pod
      # IP separation isn't meaningful here.
      local.pod_subnet_id_parameter,
      length(pool.optional_parameters) == 0 ?
      "" :
      join(" ", [
        for param in pool.optional_parameters :
        format("--%s %s", param.name, param.value)
      ]),
    ])
  }

  key_management_service = (
    var.aks_cli_config.kms_config != null
    ) ? {
    key_vault_id = try(
      var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].id,
      error("Specified kms_key_vault_name '${var.aks_cli_config.kms_config.key_vault_name}' does not exist in Key Vaults: ${join(", ", keys(var.key_vaults))}")
    )
    key_vault_key_id = try(
      var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].keys[var.aks_cli_config.kms_config.key_name].id,
      error("Specified kms_key_name '${var.aks_cli_config.kms_config.key_name}' does not exist in Key Vault '${var.aks_cli_config.kms_config.key_vault_name}' keys: ${join(", ", keys(var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].keys))}")
    )
    key_vault_key_resource_id = try(
      var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].keys[var.aks_cli_config.kms_config.key_name].resource_id,
      error("Specified kms_key_name '${var.aks_cli_config.kms_config.key_name}' does not exist in Key Vault '${var.aks_cli_config.kms_config.key_vault_name}' keys: ${join(", ", keys(var.key_vaults[var.aks_cli_config.kms_config.key_vault_name].keys))}")
    )
  } : null

  # Disk Encryption Set for OS disk encryption with Customer-Managed Keys
  # Reference: https://learn.microsoft.com/en-us/azure/aks/azure-disk-customer-managed-keys
  disk_encryption_set_id = (
    var.aks_cli_config.disk_encryption_set_name != null ?
    try(
      var.disk_encryption_sets[var.aks_cli_config.disk_encryption_set_name],
      error("Specified disk_encryption_set_name '${var.aks_cli_config.disk_encryption_set_name}' does not exist in Disk Encryption Sets: ${join(", ", keys(var.disk_encryption_sets))}")
    ) : null
  )

  kubernetes_version = (
    var.aks_cli_config.kubernetes_version == null ?
    "" :
    format(
      "%s %s",
      "--kubernetes-version", var.aks_cli_config.kubernetes_version,
    )
  )

  aks_subnet_id = (
    var.aks_cli_config.subnet_name == null ?
    null :
    try(var.subnets_map[var.aks_cli_config.subnet_name], null)
  )

  pod_subnet_id = (
    try(var.aks_cli_config.pod_subnet_name, null) == null ?
    null :
    try(var.subnets_map[var.aks_cli_config.pod_subnet_name], null)
  )

  api_server_subnet_id = (
    var.aks_cli_config.api_server_subnet_name == null ?
    null :
    try(var.subnets_map[var.aks_cli_config.api_server_subnet_name], null)
  )

  aks_custom_headers_flags = (
    length(var.aks_cli_config.aks_custom_headers) == 0 ?
    "" :
    format(
      "%s %s",
      "--aks-custom-headers",
      join(",", var.aks_cli_config.aks_custom_headers),
    )
  )

  optional_parameters = (
    length(var.aks_cli_config.optional_parameters) == 0 ?
    "" :
    join(" ", [
      for param in var.aks_cli_config.optional_parameters :
      format("--%s %s", param.name, param.value)
    ])
  )


  kms_parameters = (
    local.key_management_service == null || var.aks_cli_config.managed_identity_name == null ?
    "" :
    join(" ", compact([
      "--enable-azure-keyvault-kms",
      format("--azure-keyvault-kms-key-id %s", local.key_management_service.key_vault_key_id),
      format("--azure-keyvault-kms-key-vault-network-access %s", var.aks_cli_config.kms_config.network_access),
      var.aks_cli_config.kms_config.network_access == "Private" ? format("--azure-keyvault-kms-key-vault-resource-id %s", local.key_management_service.key_vault_id) : null
    ]))
  )

  aks_kms_role_assignments = var.aks_cli_config.managed_identity_name != null && local.key_management_service != null ? merge(
    {
      "Key Vault Crypto Service Encryption User" = local.key_management_service.key_vault_key_resource_id
      "Key Vault Crypto User"                    = local.key_management_service.key_vault_id
    },
    # When KMS uses a private endpoint, the AKS identity must be able to approve
    # the private endpoint connection on the Key Vault (PrivateEndpointConnectionsApproval/action).
    # Key Vault Contributor includes that action.
    var.aks_cli_config.kms_config.network_access == "Private" ? {
      "Key Vault Contributor" = local.key_management_service.key_vault_id
    } : {}
  ) : {}

  # Disk Encryption Set parameters for OS disk encryption with Customer-Managed Keys
  disk_encryption_parameters = (
    local.disk_encryption_set_id == null ?
    "" :
    format("--node-osdisk-diskencryptionset-id %s", local.disk_encryption_set_id)
  )

  subnet_id_parameter = (local.aks_subnet_id == null ?
    "" :
    format(
      "%s %s",
      "--vnet-subnet-id", local.aks_subnet_id,
    )
  )

  pod_subnet_id_parameter = (local.pod_subnet_id == null ?
    "" :
    format(
      "%s %s",
      "--pod-subnet-id", local.pod_subnet_id,
    )
  )

  managed_identity_parameter = (var.aks_cli_config.managed_identity_name == null ?
    "--enable-managed-identity" :
    format(
      "%s %s",
      "--assign-identity", azurerm_user_assigned_identity.userassignedidentity[0].id,
    )
  )

  kubelet_identity_parameter = (!var.enable_kubelet_identity || var.aks_cli_config.dry_run) ? "" : format(
    "%s %s",
    "--assign-kubelet-identity",
    azurerm_user_assigned_identity.kubelet_identity[0].id,
  )

  bootstrap_parameters = join(" ", compact([
    var.bootstrap_artifact_source != null ? format("--bootstrap-artifact-source %s", var.bootstrap_artifact_source) : null,
    var.bootstrap_container_registry_resource_id != null ? format("--bootstrap-container-registry-resource-id %s", var.bootstrap_container_registry_resource_id) : null,
  ]))


  api_server_vnet_integration_parameter = (var.aks_cli_config.enable_apiserver_vnet_integration && local.api_server_subnet_id != null ?
    format(
      "--enable-apiserver-vnet-integration --apiserver-subnet-id %s",
      local.api_server_subnet_id,
    ) :
    ""
  )

  aad_parameter = (
    var.aks_aad_enabled == true ?
    format(
      "--enable-aad --enable-azure-rbac --aad-admin-group-object-ids %s --aad-tenant-id %s",
      data.azurerm_client_config.current.object_id,
      data.azurerm_client_config.current.tenant_id
    )
    : ""
  )

  custom_configurations = (
    var.aks_cli_config.use_custom_configurations && var.aks_cli_custom_config_path != null ?
    format(
      "--custom-configuration %s",
      var.aks_cli_custom_config_path
    ) :
    ""
  )

  default_node_pool_parameters = (
    var.aks_cli_config.default_node_pool == null ? [] : [
      "--nodepool-name", var.aks_cli_config.default_node_pool.name,
      "--node-count", var.aks_cli_config.default_node_pool.node_count,
      "--node-vm-size", var.aks_cli_config.default_node_pool.vm_size,
      "--vm-set-type", var.aks_cli_config.default_node_pool.vm_set_type,
      "--node-osdisk-type", var.aks_cli_config.default_node_pool.os_disk_type,
    ]
  )

  aks_cli_command = join(" ", concat([
    "az",
    "aks",
    "create",
    "-g", var.resource_group_name,
    "-n", var.aks_cli_config.aks_name,
    "--location", var.location,
    "--tier", var.aks_cli_config.sku_tier,
    "--tags", join(" ", local.tags_list),
    local.aks_custom_headers_flags,
    local.custom_configurations,
    "--no-ssh-key",
    local.kubernetes_version,
    local.bootstrap_parameters,
    local.optional_parameters,
    local.kms_parameters,
    local.disk_encryption_parameters,
    local.subnet_id_parameter,
    local.pod_subnet_id_parameter,
    local.managed_identity_parameter,
    local.kubelet_identity_parameter,
    local.api_server_vnet_integration_parameter,
    local.aad_parameter,
  ], local.default_node_pool_parameters))

  aks_cli_destroy_command = join(" ", [
    "az",
    "aks",
    "delete",
    "-g", var.resource_group_name,
    "-n", var.aks_cli_config.aks_name,
    "--yes",
  ])
}

data "azurerm_client_config" "current" {}

locals {
  resource_group_id = format(
    "/subscriptions/%s/resourceGroups/%s",
    data.azurerm_client_config.current.subscription_id,
    var.resource_group_name
  )
}

resource "azurerm_user_assigned_identity" "userassignedidentity" {
  count               = var.aks_cli_config.managed_identity_name == null ? 0 : 1
  location            = var.location
  name                = var.aks_cli_config.managed_identity_name
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_user_assigned_identity" "kubelet_identity" {
  count               = (!var.aks_cli_config.dry_run && var.enable_kubelet_identity) ? 1 : 0
  location            = var.location
  name                = "${var.aks_cli_config.aks_name}-kubelet-identity"
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "network_contributor" {
  count                = var.aks_cli_config.managed_identity_name != null && var.aks_cli_config.subnet_name != null ? 1 : 0
  role_definition_name = "Network Contributor"
  scope                = local.aks_subnet_id
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

resource "azurerm_role_assignment" "network_contributor_api_server_subnet" {
  count = (var.aks_cli_config.managed_identity_name != null && var.aks_cli_config.enable_apiserver_vnet_integration) ? 1 : 0

  role_definition_name = "Network Contributor"
  scope                = local.api_server_subnet_id
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

# Grant AcrPull access to ACR for kubelet identity (node identity) BEFORE cluster creation.
resource "azurerm_role_assignment" "acr_pull_kubelet" {
  for_each = local.acr_pull_scopes_for_each

  scope                = each.value
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.kubelet_identity[0].principal_id
}

# If the cluster uses a user-assigned identity, it must be able to assign/use the kubelet identity.
resource "azurerm_role_assignment" "managed_identity_operator_kubelet" {
  count = (!var.aks_cli_config.dry_run && var.enable_kubelet_identity && var.aks_cli_config.managed_identity_name != null) ? 1 : 0

  scope                = azurerm_user_assigned_identity.kubelet_identity[0].id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

resource "terraform_data" "enable_aks_cli_preview_extension" {
  count = var.aks_cli_config.use_aks_preview_cli_extension == true ? 1 : 0

  # Todo - Update aks-preview extension for newer features
  provisioner "local-exec" {
    command = var.aks_cli_config.use_aks_preview_private_build == true ? (
      <<EOT
			wget https://telescopetools.z13.web.core.windows.net/packages/az-cli/aks_preview-14.0.0b6-py2.py3-none-any.whl
			az extension add --source ./aks_preview-14.0.0b6-py2.py3-none-any.whl -y
			az version
    EOT
      ) : (
      <<EOT
      az extension add -n aks-preview --version 19.0.0b27
      az version
    EOT
    )
  }

  provisioner "local-exec" {
    when    = destroy
    command = "az extension remove -n aks-preview 2>/dev/null || true"
  }
}

resource "terraform_data" "aks_cli" {
  depends_on = [
    terraform_data.enable_aks_cli_preview_extension,
    azurerm_role_assignment.network_contributor,
    azurerm_role_assignment.network_contributor_api_server_subnet,
    azurerm_role_assignment.aks_identity_kms_roles,
    azurerm_role_assignment.acr_pull_kubelet,
    azurerm_role_assignment.managed_identity_operator_kubelet
  ]

  input = {
    aks_cli_command         = var.aks_cli_config.dry_run ? "echo '${local.aks_cli_command}'" : local.aks_cli_command,
    aks_cli_destroy_command = var.aks_cli_config.dry_run ? "echo '${local.aks_cli_destroy_command}'" : local.aks_cli_destroy_command
  }

  provisioner "local-exec" {
    # Wrap `az aks create` in a retry loop for transient Azure RP errors
    # that are recoverable by waiting:
    #
    #   - ReferencedResourceNotProvisioned: subnet (or other referenced
    #     resource) is in `Updating` state when AKS tries to use it. At
    #     shared-VNet scale (200 subnets / 100 AKS in clustermesh-scale
    #     N=100), Azure serializes ALL subnet operations per-VNet — only
    #     one PutSubnetOperation can be in flight at a time. With 100
    #     concurrent AKS creates all attaching to different subnets in
    #     the same shared VNet, the per-VNet serialization queue forces
    #     some AKS creates to see a peer cluster's subnet PUT mid-flight
    #     and reject with this error. Retry resolves it once the queue
    #     drains.
    #   - OperationNotAllowed / AnotherOperationInProgress: same race
    #     pattern as aks_nodepool_cli below; another in-progress operation
    #     on the AKS / VNet / RG blocks the create. Retry.
    #
    # Strictly additive: first attempt = original behavior. Other
    # Telescope scenarios (single-cluster, peered, etc.) hit zero retries
    # on the happy path. Only the few clusters that lose the serialization
    # race at N=100 shared-VNet pay the retry cost.
    #
    # Budget: 30 retries × 60s = 30 min. Enough for the worst Azure VNet
    # propagation tail observed in clustermesh-scale runs.
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -uo pipefail
      cmd=${jsonencode(self.input.aks_cli_command)}
      rg="${var.resource_group_name}"
      name="${var.aks_cli_config.aks_name}"
      for i in $(seq 1 15); do
        out=$(eval "$cmd" 2>&1) && { echo "$out"; exit 0; }
        rc=$?
        echo "$out"
        # Retryable Azure RP errors. All point to transient resource-busy
        # / serialization conditions that recover once the queue drains:
        #   - ReferencedResourceNotProvisioned: subnet (or other) in Updating
        #     state when AKS tried to use it.
        #   - VirtualNetworkNotInSucceededState: VNet itself in Updating
        #     state during AKS create — broader cousin of the above
        #     (build 67775 + 67788 evidence at N=100 shared-VNet).
        #   - OperationNotAllowed / AnotherOperationInProgress: another
        #     in-progress op on AKS/VNet/RG blocks the create (same race
        #     pattern as aks_nodepool_cli below).
        #   - RetryableError: catch-all from azure-cli's own classifier.
        #   - ResourceAlreadyExists: prior attempt half-created the cluster
        #     before failing. We MUST delete it before retrying — without
        #     the delete, every subsequent `az aks create` for the same
        #     name returns AlreadyExists and we never recover.
        retryable=0
        if echo "$out" | grep -qE "ReferencedResourceNotProvisioned|VirtualNetworkNotInSucceededState|OperationNotAllowed|AnotherOperationInProgress|RetryableError|ResourceAlreadyExists|AlreadyExists"; then
          retryable=1
        fi
        if [ "$retryable" -eq 0 ]; then
          # Non-retryable failure (quota, invalid args, auth, etc.) — fail fast.
          exit $rc
        fi

        # Build 67788 evidence: VirtualNetworkNotInSucceededState during
        # `az aks create` at N=100 shared-VNet leaves the cluster half-
        # created in Failed state. On retry, az aks create returns
        # AlreadyExists and we're stuck. Detect the Failed (or any non-
        # Succeeded existing) cluster and DELETE it before retrying.
        existing_state=$(az aks show -g "$rg" -n "$name" --query provisioningState -o tsv --only-show-errors 2>/dev/null || echo "absent")
        if [ "$existing_state" != "absent" ] && [ "$existing_state" != "Succeeded" ]; then
          echo "[aks_cli retry $i/15] $name exists in state '$existing_state' from failed prior attempt; deleting before retry"
          az aks delete -g "$rg" -n "$name" --yes --only-show-errors 2>&1 || \
            echo "[aks_cli retry $i/15] az aks delete reported error; continuing anyway"
          # Confirm delete completed (or at least the cluster is no longer
          # listable). Up to 10 min budget — typical AKS delete is 3-5 min.
          for j in $(seq 1 30); do
            cur=$(az aks show -g "$rg" -n "$name" --query provisioningState -o tsv --only-show-errors 2>/dev/null || echo "absent")
            if [ "$cur" = "absent" ]; then
              echo "[aks_cli retry $i/15] $name fully deleted; proceeding with recreate"
              break
            fi
            echo "[aks_cli retry $i/15] $name still present (state=$cur), waiting 20s..."
            sleep 20
          done
        fi
        echo "[aks_cli retry $i/15] transient Azure RP error; sleeping 60s before retry"
        sleep 60
      done
      echo "[aks_cli] gave up after 15 retries — Azure RP not stabilizing" >&2
      exit 1
    EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = self.input.aks_cli_destroy_command
  }
}

# Gate any subsequent `az aks ...` operations (extra node pools, post-create
# updates) on the cluster reaching a stable provisioningState=Succeeded.
#
# Why this exists: `az aks create --enable-acns` (and similar addon flags
# like --enable-azure-monitor-metrics) kicks off a PutExtensionAddonHandler
# PUT operation that runs ASYNCHRONOUSLY after `az aks create` returns. While
# that operation is in flight, any downstream `az aks nodepool add` (e.g. our
# extra_node_pool / prompool) fails with:
#   ERROR: (OperationNotAllowed) Operation is not allowed because there's an
#   in progress PutExtensionAddonHandler.PUT operation ... Please wait for it
#   to finish before starting a new operation.
# The race is timing-dependent and rarely manifests with 1-2 concurrent
# cluster creates, but is deterministic at N>=5 (regional AKS RP queues the
# extension installs and the slowest cluster's PUT lags `az aks create` return
# by several minutes — observed in the clustermesh-scale n5 tier).
#
# Polling logic: require 3 consecutive Succeeded readings 20s apart, with a
# 60s initial buffer so any queued extension install has time to transition
# the cluster into Updating. The consecutive requirement defends against the
# brief Succeeded window between create-finish and extension-start. Total
# budget ~20m.
resource "terraform_data" "aks_wait_succeeded" {
  count = var.aks_cli_config.dry_run ? 0 : 1

  depends_on = [terraform_data.aks_cli]

  input = {
    resource_group_name = var.resource_group_name
    aks_name            = var.aks_cli_config.aks_name
  }

  provisioner "local-exec" {
    # local-exec defaults to /bin/sh which on Ubuntu agents is dash; dash
    # rejects `set -o pipefail` (bash-only). Explicitly select bash so the
    # script's safety options work as written.
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -eo pipefail
      rg="${self.input.resource_group_name}"
      name="${self.input.aks_name}"
      echo "Waiting for AKS $name to reach a stable Succeeded state..."
      sleep 60
      required=3
      got=0
      # 90 attempts × 20s = 30 min budget. Bumped from 60 (20m) for N=100
      # ClusterMesh runs — plan.md deferred #10 observed a single cluster
      # oscillate Updating/Succeeded for ~17 min at N=20. With 100 concurrent
      # creates we expect a handful of clusters to exceed the old 20m budget
      # purely from AKS RP throttling under concurrency. Strictly additive
      # — fast clusters exit early at ~1m via the 3-consecutive-Succeeded
      # check; only slow outliers pay the longer ceiling.
      #
      # Fail-fast on terminal Failed state (build 67775 evidence at N=100):
      # async ACNS addon PUTs can move a cluster from Updating → Failed AFTER
      # `az aks create` returned. Without this fail-fast, the poll loop
      # wastes the full 30 min before exiting 1, then preserve_state retries
      # the wait twice more = 1.5h burned per failed cluster. Detecting
      # Failed early lets terraform surface the error in ~1 min so the
      # operator can react (drop parallelism, taint, etc.).
      for i in $(seq 1 90); do
        state=$(az aks show -g "$rg" -n "$name" --query provisioningState -o tsv 2>/dev/null || echo "Unknown")
        if [ "$state" = "Succeeded" ]; then
          got=$((got + 1))
          if [ "$got" -ge "$required" ]; then
            echo "AKS $name stable in Succeeded ($got consecutive checks). Continuing."
            exit 0
          fi
        elif [ "$state" = "Failed" ]; then
          # Terminal failure — no point polling further. Recovery (delete +
          # recreate, or `az aks update` per the AKS RP error message) is
          # outside this wait's contract; surface the error now.
          echo "AKS $name is in terminal Failed state — fail-fast (not polling further)"
          exit 1
        else
          if [ "$got" -gt 0 ]; then
            echo "AKS $name re-entered '$state' after Succeeded streak; resetting counter"
          fi
          got=0
        fi
        echo "AKS $name provisioningState=$state (Succeeded streak=$got/$required)"
        sleep 20
      done
      echo "Timeout: AKS $name did not reach sustained Succeeded after ~30m"
      exit 1
    EOT
  }
}

resource "terraform_data" "aks_nodepool_cli" {
  depends_on = [
    terraform_data.aks_cli,
    terraform_data.aks_wait_succeeded,
  ]

  for_each = local.extra_pool_map

  # Wrap the underlying `az aks nodepool add` (built in locals.extra_pool_commands)
  # in a bash retry loop that handles the OperationNotAllowed / AnotherOperationInProgress
  # AKS RP race window. Even with terraform_data.aks_wait_succeeded gating
  # this on a stable cluster Succeeded state, the AKS RP can lazily start
  # post-create extension PUTs (e.g. --enable-acns) AFTER the wait exits —
  # observed at N>=5 cluster create concurrency where the regional RP queues
  # addon installs minutes behind the parent cluster create. The retry catches
  # that race; keeping the wait avoids noisy first-attempt failures in the
  # common (non-lazy) case. 60 retries * 30s = 30min budget. Bumped from
  # 30 (15min) for N=100 ClusterMesh runs — at 100 concurrent cluster
  # creates the AKS RP queue can hold nodepool-add operations behind
  # cluster-create operations far longer than at smaller N.
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -eo pipefail
      cmd=${jsonencode(local.extra_pool_commands[each.key])}
      pool="${each.value.name}"
      cluster="${var.aks_cli_config.aks_name}"
      for i in $(seq 1 60); do
        out=$(eval "$cmd" 2>&1) && { echo "$out"; exit 0; }
        if echo "$out" | grep -qE "OperationNotAllowed|AnotherOperationInProgress"; then
          echo "[retry $i/60] $cluster nodepool $pool create blocked by in-progress AKS RP operation; sleeping 30s"
          sleep 30
          continue
        fi
        # Some other failure (quota, invalid args, etc.) — fail fast.
        echo "$out" >&2
        exit 1
      done
      echo "Timeout: $cluster nodepool $pool create still blocked after 60 retries (~30m)" >&2
      exit 1
    EOT
  }
}

# Grant AKS identity KMS-related Key Vault roles
resource "azurerm_role_assignment" "aks_identity_kms_roles" {
  for_each             = local.aks_kms_role_assignments
  scope                = each.value
  role_definition_name = each.key
  principal_id         = azurerm_user_assigned_identity.userassignedidentity[0].principal_id
}

data "azapi_resource" "aks" {
  count = var.aks_cli_config.disk_encryption_set_name != null && !var.aks_cli_config.dry_run ? 1 : 0

  depends_on = [terraform_data.aks_cli]

  type      = "Microsoft.ContainerService/managedClusters@2024-10-01"
  name      = var.aks_cli_config.aks_name
  parent_id = local.resource_group_id

  # Keep the payload small but sufficient for DES role assignments.
  response_export_values = [
    "identity",
    "properties.identityProfile",
  ]
}

locals {
  aks_identity_for_des = (var.aks_cli_config.disk_encryption_set_name != null && !var.aks_cli_config.dry_run) ? data.azapi_resource.aks[0].output : null

  aks_kubelet_object_id = try(
    local.aks_identity_for_des.properties.identityProfile.kubeletidentity.objectId,
    local.aks_identity_for_des.properties.identityProfile.kubeletIdentity.objectId,
    null
  )

  aks_system_assigned_principal_id = try(local.aks_identity_for_des.identity.principalId, null)
}

# Grant Reader access to Disk Encryption Set for kubelet identity
resource "azurerm_role_assignment" "des_reader_kubelet" {
  count = var.aks_cli_config.disk_encryption_set_name != null && !var.aks_cli_config.dry_run ? 1 : 0

  scope                = local.disk_encryption_set_id
  role_definition_name = "Reader"
  principal_id         = local.aks_kubelet_object_id != null ? local.aks_kubelet_object_id : error("Unable to determine AKS kubelet identity objectId via azapi; cannot grant DES Reader role.")
}

# Grant Reader access to Disk Encryption Set for cluster identity
resource "azurerm_role_assignment" "des_reader_cluster" {
  count = var.aks_cli_config.disk_encryption_set_name != null && !var.aks_cli_config.dry_run ? 1 : 0

  scope                = local.disk_encryption_set_id
  role_definition_name = "Reader"
  principal_id = var.aks_cli_config.managed_identity_name != null ? azurerm_user_assigned_identity.userassignedidentity[0].principal_id : (
    local.aks_system_assigned_principal_id != null ? local.aks_system_assigned_principal_id : error("Unable to determine AKS system-assigned identity principalId via azapi; cannot grant DES Reader role.")
  )
}

