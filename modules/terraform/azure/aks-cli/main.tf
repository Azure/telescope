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
        # Idempotency precheck (build 67798 evidence): under
        # preserve_state_on_apply_failure + AzDO retryCountOnTaskFailure,
        # terraform may re-run this local-exec against a cluster that the
        # previous attempt ALREADY created. Without this precheck the
        # second `az aks create` returns "already exists" and the build
        # fails with no recovery. Three cases:
        #   - Cluster exists in Succeeded: nothing to do, return success
        #   - Cluster exists in non-Succeeded (Failed/Updating/Creating):
        #     stale half-created state from a prior attempt — delete and
        #     re-create
        #   - Cluster absent: proceed with create
        existing_state=$(az aks show -g "$rg" -n "$name" --query provisioningState -o tsv --only-show-errors 2>/dev/null || echo "absent")
        if [ "$existing_state" = "Succeeded" ]; then
          echo "[aks_cli retry $i/15] $name already exists in Succeeded state from prior apply attempt; nothing to do"
          exit 0
        fi
        if [ "$existing_state" != "absent" ]; then
          echo "[aks_cli retry $i/15] $name exists in state '$existing_state' (stale half-created); deleting before recreate"
          az aks delete -g "$rg" -n "$name" --yes --only-show-errors 2>&1 || \
            echo "[aks_cli retry $i/15] az aks delete reported error; continuing anyway"
          # Confirm delete completed (or at least no longer listable).
          # Up to 10 min budget — typical AKS delete is 3-5 min.
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

        out=$(eval "$cmd" 2>&1) && { echo "$out"; exit 0; }
        rc=$?
        echo "$out"
        # Retryable Azure RP errors. All point to transient resource-busy
        # / serialization conditions that recover once the queue drains.
        # Match BOTH the CamelCase code text (in JSON details[]) AND the
        # az CLI's friendlier English text (e.g. "already exists") via
        # case-insensitive grep.
        #   - ReferencedResourceNotProvisioned: subnet (or other) in Updating
        #     state when AKS tried to use it.
        #   - VirtualNetworkNotInSucceededState: VNet itself in Updating
        #     state during AKS create — broader cousin of the above
        #     (build 67775 + 67788 evidence at N=100 shared-VNet).
        #   - OperationNotAllowed / AnotherOperationInProgress: another
        #     in-progress op on AKS/VNet/RG blocks the create.
        #   - RetryableError: catch-all from azure-cli's own classifier.
        #   - already exists: friendly English text for ResourceAlreadyExists
        #     (build 67798 evidence: az CLI emits "The cluster 'X' under
        #     resource group 'Y' already exists" not "ResourceAlreadyExists"
        #     in stdout — original CamelCase-only grep missed this).
        if echo "$out" | grep -qiE "ReferencedResourceNotProvisioned|VirtualNetworkNotInSucceededState|OperationNotAllowed|AnotherOperationInProgress|RetryableError|already[[:space:]]*exists"; then
          echo "[aks_cli retry $i/15] transient Azure RP error; sleeping 60s before retry"
          sleep 60
          continue
        fi
        # OutboundConnFail at recreate-into-VNet-flux (build 68700 evidence):
        # when our delete+recreate logic above lands a fresh VMSS during
        # shared-VNet subnet PUT flux at N=100, CSE script can't reach
        # outbound -> VMExtensionError_OutboundConnFail. NOT a general retry
        # (would mask real outbound config bugs at smaller N + bleed time
        # at N=100). Allow ONE retry only, and only on the FIRST attempt
        # after our recreate logic — past that, fail-fast.
        if [ "$i" -le 2 ] && echo "$out" | grep -qiE "VMExtensionError_OutboundConnFail|VMExtensionProvisioningError.*OutboundConnFail"; then
          echo "[aks_cli retry $i/15] OutboundConnFail at fresh create; allowing 1 retry for VNet flux window; sleeping 120s"
          # Clean up the partial cluster before retry: otherwise we hit
          # "already exists" or compound VMSS orphans.
          az aks delete -g "$rg" -n "$name" --yes --only-show-errors 2>&1 || \
            echo "[aks_cli retry $i/15] partial cleanup delete reported error; continuing"
          # 5 min budget for partial cleanup to release the bricked VMSS.
          for k in $(seq 1 15); do
            cur=$(az aks show -g "$rg" -n "$name" --query provisioningState -o tsv --only-show-errors 2>/dev/null || echo "absent")
            [ "$cur" = "absent" ] && break
            sleep 20
          done
          sleep 120
          continue
        fi
        # Non-retryable failure (quota, invalid args, auth, etc.) — fail fast.
        exit $rc
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
      # Track stuck-Updating: build 68577 mesh-44 evidence — AKS RP can
      # park a cluster in Updating for hours with no forward progress
      # (regional throttling under N=100 concurrency). Without fast-fail
      # the wait burns its full 30min ceiling on each AzDO retry. Detect:
      # if state hasn't transitioned for STUCK_THRESHOLD consecutive
      # iterations (~20min at 20s poll), declare stuck and abort.
      #
      # Build 69155 evidence: stuck_threshold=30 (10min) false-positived
      # on n=2 happy-path clusters during normal post-create ACNS
      # reconciliation (clusters legitimately stay in Updating ~10-15min
      # before reaching Succeeded). Bumped 30 -> 60 (20min) so the
      # detection still saves 10min vs the 30min ceiling on genuine
      # stuck cases but won't fire during normal reconciliation.
      prev_state=""
      same_state_count=0
      stuck_threshold=60
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
        # Stuck-state fast-fail: same non-terminal state for stuck_threshold
        # consecutive iterations = no forward progress = abort.
        if [ "$state" = "$prev_state" ]; then
          same_state_count=$((same_state_count + 1))
          if [ "$same_state_count" -ge "$stuck_threshold" ]; then
            echo "AKS $name STUCK in state '$state' for $((same_state_count * 20))s with no progress — fail-fast (not polling further)"
            exit 1
          fi
        else
          same_state_count=0
          prev_state="$state"
        fi
        echo "AKS $name provisioningState=$state (Succeeded streak=$got/$required, same-state=$same_state_count/$stuck_threshold)"
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
  #
  # Idempotency precheck (build 68577 evidence): under
  # preserve_state_on_apply_failure + AzDO retryCountOnTaskFailure, terraform
  # may re-run this local-exec against a cluster whose nodepool was ALREADY
  # added by a previous apply attempt that then failed at a different step.
  # Without precheck the next `az aks nodepool add` returns "already exists"
  # and the build fails deterministically — observed across multiple stage
  # retries of build 68577. Mirrors the precheck pattern used by aks_cli
  # (above) but with state-aware recovery:
  #   - Succeeded: idempotent success
  #   - Creating/Updating/Deleting: wait (do NOT delete healthy in-flight ops)
  #   - Failed: delete and recreate (terminal only)
  #   - absent: proceed with add
  #
  # BRICKED-DELETE FAST-FAIL (build 69021 evidence): when nodepool is in
  # Failed state and `az aks nodepool delete` is called, Azure should
  # transition the state Failed -> Deleting within seconds. If state stays
  # Failed after the delete API call, Azure RP rejected the delete and
  # the nodepool is BRICKED — no amount of additional polling will help.
  # Build 69021 N=50 g100 burned 13.6 HOURS because the old logic waited
  # the full 90min overall deadline polling a Failed nodepool that would
  # never delete. Fast-fail: if state hasn't transitioned out of Failed
  # within DELETE_TRANSITION_BUDGET seconds after issuing delete, abort
  # immediately rather than burning the full retry budget.
  #
  # META PRINCIPLE: any retry loop where the same state is observed
  # across 5+ consecutive iterations without forward progress should
  # escalate to fail-fast. Slow retries on terminal failures are how
  # 14h builds happen. Cheap retries (transient API throttle, brief
  # race window) are valuable; bricked-state retries are not.
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -uo pipefail
      cmd=${jsonencode(local.extra_pool_commands[each.key])}
      rg="${var.resource_group_name}"
      pool="${each.value.name}"
      cluster="${var.aks_cli_config.aks_name}"
      deadline=$((SECONDS + 5400))

      for i in $(seq 1 60); do
        if [ "$SECONDS" -ge "$deadline" ]; then
          echo "Timeout: $cluster nodepool $pool — 90m overall deadline reached" >&2
          exit 1
        fi

        # Precheck — classify show failures so transient throttle/auth
        # errors don't get silently treated as "absent" (which would
        # cause a spurious add attempt that hides the real error).
        show_out=$(az aks nodepool show -g "$rg" --cluster-name "$cluster" -n "$pool" --query provisioningState -o tsv --only-show-errors 2>&1)
        show_rc=$?
        if [ "$show_rc" -eq 0 ]; then
          existing_state="$show_out"
        elif echo "$show_out" | grep -qiE "NotFound|could not be found|ResourceNotFound"; then
          existing_state="absent"
        else
          echo "[retry $i/60] $cluster nodepool $pool show failed transiently: $show_out — sleeping 30s"
          sleep 30
          continue
        fi

        case "$existing_state" in
          Succeeded)
            echo "[retry $i/60] $cluster nodepool $pool already in Succeeded state from prior apply attempt; nothing to do"
            exit 0
            ;;
          Creating|Updating|Deleting)
            # Still converging from prior attempt. Wait rather than
            # destructively delete — the pool may reach Succeeded on
            # its own, and deleting an in-flight op queues a delete
            # behind it (extra churn at N=100 AKS RP scale).
            echo "[retry $i/60] $cluster nodepool $pool in transient state '$existing_state'; waiting 30s"
            sleep 30
            continue
            ;;
          Failed)
            # Terminal failure — delete and recreate. BRICKED-DELETE
            # fast-fail: watch for state transition Failed → Deleting
            # within 120s of the delete call. If state stays Failed,
            # the nodepool is bricked (Azure RP rejected delete) and
            # no further polling will help — abort immediately rather
            # than burning the full 60×30s retry budget (build 69021
            # evidence: 13.6h wasted on this exact pattern).
            echo "[retry $i/60] $cluster nodepool $pool in terminal Failed state; deleting before recreate"
            del_out=$(az aks nodepool delete -g "$rg" --cluster-name "$cluster" -n "$pool" --yes --only-show-errors 2>&1) || \
              echo "[retry $i/60] az aks nodepool delete reported error (will poll absence anyway): $del_out"
            # Up to 10 min budget — typical AKS nodepool delete is 2-4 min.
            deleted=false
            transitioned=false
            for j in $(seq 1 30); do
              cur=$(az aks nodepool show -g "$rg" --cluster-name "$cluster" -n "$pool" --query provisioningState -o tsv --only-show-errors 2>/dev/null || echo "absent")
              if [ "$cur" = "absent" ]; then
                echo "[retry $i/60] $cluster nodepool $pool fully deleted; will recreate on next iteration"
                deleted=true
                break
              fi
              # Track transition out of Failed → bricked detection
              if [ "$cur" != "Failed" ]; then
                transitioned=true
              fi
              # Bricked fast-fail: 120s elapsed (6 × 20s) and still Failed.
              if [ "$j" -ge 6 ] && [ "$transitioned" != "true" ] && [ "$cur" = "Failed" ]; then
                echo "[retry $i/60] $cluster nodepool $pool BRICKED — state still Failed 120s after delete call (Azure RP rejected delete). Aborting; no further retry will help." >&2
                exit 1
              fi
              echo "[retry $i/60] $cluster nodepool $pool still present (state=$cur), waiting 20s..."
              sleep 20
            done
            if [ "$deleted" != "true" ]; then
              echo "[retry $i/60] $cluster nodepool $pool delete did not complete in 10m; re-precheck on next iteration"
              sleep 30
            fi
            continue
            ;;
          absent)
            ;;
          *)
            echo "[retry $i/60] $cluster nodepool $pool in unknown state '$existing_state'; waiting 30s"
            sleep 30
            continue
            ;;
        esac

        # Nodepool absent — attempt add.
        out=$(eval "$cmd" 2>&1) && { echo "$out"; exit 0; }
        rc=$?
        echo "$out"
        # Retryable Azure RP errors:
        #   - OperationNotAllowed / AnotherOperationInProgress: AKS RP busy
        #     with another op on the cluster (e.g. lazy ACNS addon PUT
        #     post-create). Retry once the queue drains.
        #   - already exists: a concurrent/very-recent apply attempt
        #     created the nodepool between our precheck and add. Retry —
        #     next precheck will see Succeeded/Updating and resolve.
        if echo "$out" | grep -qiE "OperationNotAllowed|AnotherOperationInProgress|already[[:space:]]*exists"; then
          echo "[retry $i/60] $cluster nodepool $pool transient AKS RP error; sleeping 30s"
          sleep 30
          continue
        fi
        # Some other failure (quota, invalid args, etc.) — fail fast.
        echo "$out" >&2
        exit $rc
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

