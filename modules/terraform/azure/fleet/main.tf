# =============================================================================
# Fleet + ClusterMesh Profile submodule
#
# Mirrors Steps 4-6 of fleet-setup-script.sh:
#   Step 4: az fleet create
#   Step 5: az fleet member create --labels mesh=true  (per cluster)
#   Step 6: az fleet clustermeshprofile create --selector mesh=true
#           az fleet clustermeshprofile apply
#
# Design decisions:
# - Fleet resource: azapi_resource. There is no stable azurerm resource that
#   covers managed Fleet with the shape we need, and the clustermeshprofile
#   lives under the same ARM parent, so keeping Fleet in azapi keeps the
#   parent_id references simple.
# - Fleet members: terraform_data + local-exec wrapping
#   `az fleet member create --labels`. Member labels (needed by the
#   clustermeshprofile selector) are first-class in the Fleet ARM API but
#   the azapi resource body shape is currently rejected for this field;
#   az CLI is the supported surface today.
# - ClusterMeshProfile create/apply: terraform_data + local-exec, wrapping
#   `az fleet clustermeshprofile create` and `apply`. The ARM resource type
#   is still private-preview — az CLI (v2.0.4+ private .whl) is currently
#   the only path. Create and destroy commands are stored inside
#   terraform_data.input so the destroy-time provisioner can reference
#   self.input.<cmd> (destroy-time provisioners can't read vars/locals).
#   Same pattern as modules/terraform/azure/aks-cli/main.tf:271-318.
# =============================================================================

locals {
  fleet_enabled = var.fleet_enabled

  members_by_name = { for m in var.members : m.member_name => m }

  # Construct AKS resource IDs from known inputs. aks-cli does not emit outputs.
  # The depends_on chain on the fleet module instance ensures AKS exists before
  # these IDs are referenced by the member create call.
  aks_resource_id = {
    for m in var.members :
    m.member_name => format(
      "/subscriptions/%s/resourceGroups/%s/providers/Microsoft.ContainerService/managedClusters/%s",
      var.subscription_id,
      var.resource_group_name,
      m.aks_name,
    )
  }
}

# -----------------------------------------------------------------------------
# Step 4: Fleet resource
# -----------------------------------------------------------------------------
resource "azapi_resource" "fleet" {
  count = local.fleet_enabled ? 1 : 0

  type      = "Microsoft.ContainerService/fleets@2025-03-01"
  name      = var.fleet_name
  parent_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  location  = var.location
  tags      = var.tags

  body = {
    properties = {}
  }
}

# -----------------------------------------------------------------------------
# Step 5: Fleet members (one per AKS cluster), labeled for the mesh selector.
#
# Implemented via local-exec for two reasons:
# 1. Mirrors the source script exactly (`az fleet member create --labels mesh=true`).
# 2. The Fleet member ARM API rejects azapi-style bodies for the `labels` field;
#    az CLI is the supported surface for this resource shape today.
#
# Same pattern as the clustermeshprofile below: command stored in
# terraform_data.input so destroy-time provisioner can reference self.input.*.
# -----------------------------------------------------------------------------
locals {
  member_create_command = {
    for m in var.members : m.member_name => join(" ", [
      "az fleet member create",
      "--subscription", var.subscription_id,
      "--resource-group", var.resource_group_name,
      "--fleet-name", var.fleet_name,
      "--name", m.member_name,
      "--member-cluster-id", local.aks_resource_id[m.member_name],
      "--labels", "${var.member_label_key}=${var.member_label_value}",
      "--output", "none",
    ])
  }

  member_destroy_command = {
    for m in var.members : m.member_name => join(" ", [
      "az fleet member delete",
      "--subscription", var.subscription_id,
      "--resource-group", var.resource_group_name,
      "--fleet-name", var.fleet_name,
      "--name", m.member_name,
      "--yes",
      "--output", "none",
    ])
  }

  # Re-label members during destroy so the clustermeshprofile's
  # `${member_label_key}=${member_label_value}` selector no longer matches —
  # this is the only way out of the Fleet API's chicken-and-egg between
  # `member delete` (rejects with MemberBelongsToClusterMesh while attached)
  # and `clustermeshprofile delete` (rejects with
  # CannotDeleteClusterMeshProfileWithMembers while members exist). The
  # value `detaching` is intentionally non-matching; `az fleet member update
  # --labels` REPLACES the labels map (it's not additive), so this also
  # drops the original mesh=true label.
  member_relabel_command = {
    for m in var.members : m.member_name => join(" ", [
      "az fleet member update",
      "--subscription", var.subscription_id,
      "--resource-group", var.resource_group_name,
      "--fleet-name", var.fleet_name,
      "--name", m.member_name,
      "--labels", "${var.member_label_key}=detaching",
      "--output", "none",
    ])
  }
}

resource "terraform_data" "member" {
  for_each = local.fleet_enabled ? local.members_by_name : {}

  depends_on = [azapi_resource.fleet]

  input = {
    create_command  = local.member_create_command[each.value.member_name]
    destroy_command = local.member_destroy_command[each.value.member_name]
  }

  # Bash retry loop. The Fleet RP can lag behind the AKS RP by 30-60s after
  # a fresh AKS create; without retry, `az fleet member create` returns
  # DependentResourceNotFound. Additionally, the AKS cluster can be in
  # `Updating` state for several minutes after the Network Contributor role
  # assignment on the VNet (granted in modules/terraform/azure/main.tf for the
  # clustermesh-apiserver internal LB) — `az fleet member create` rejects
  # with `ManagedClusterNotInExpectedState` until reconciliation finishes.
  # 60 x 20s = 20 min covers slow Azure days; the happy path exits on the
  # first attempt (~5s).
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      cmd='${self.input.create_command}'
      max=60
      delay=20
      for i in $(seq 1 $max); do
        echo "[$i/$max] $cmd"
        if eval "$cmd"; then
          exit 0
        fi
        if [ "$i" -lt "$max" ]; then
          echo "Fleet RP not ready yet, retrying in $${delay}s..."
          sleep "$delay"
        fi
      done
      echo "az fleet member create failed after $max attempts" >&2
      exit 1
    EOT
  }

  provisioner "local-exec" {
    when        = destroy
    interpreter = ["bash", "-c"]
    command     = "${self.input.destroy_command} || true"
  }
}

# -----------------------------------------------------------------------------
# Step 6: ClusterMesh profile (create + apply) via local-exec.
#
# Both the create and the destroy commands are stored inside
# terraform_data.input so the destroy provisioner can reference self.input.*
# (destroy-time provisioners cannot reference var.* or local.*).
#
# Destroy ordering: this resource depends on every fleet member, so on destroy
# Terraform tears down the profile BEFORE the members (and before the AKS
# clusters downstream). That matches the source-of-truth teardown: detach the
# mesh before the clusters disappear, else extension reconciliation hangs.
# -----------------------------------------------------------------------------
locals {
  cmp_create_command = local.fleet_enabled ? join(" ", [
    "az fleet clustermeshprofile create",
    "--subscription", var.subscription_id,
    "--resource-group", var.resource_group_name,
    "--fleet-name", var.fleet_name,
    "--name", var.cmp_name,
    "--selector", "${var.member_label_key}=${var.member_label_value}",
    "--output", "none",
  ]) : "true"

  cmp_apply_command = local.fleet_enabled ? join(" ", [
    "az fleet clustermeshprofile apply",
    "--subscription", var.subscription_id,
    "--resource-group", var.resource_group_name,
    "--fleet-name", var.fleet_name,
    "--name", var.cmp_name,
    "--output", "none",
  ]) : "true"

  cmp_destroy_command = local.fleet_enabled ? join(" ", [
    "az fleet clustermeshprofile delete",
    "--subscription", var.subscription_id,
    "--resource-group", var.resource_group_name,
    "--fleet-name", var.fleet_name,
    "--name", var.cmp_name,
    "--yes",
    "--output", "none",
  ]) : "true"

  # Returns the count of fleet members CURRENTLY APPLIED to the profile (i.e.
  # in the profile's reconciled member set, not just selector-matched). Used
  # by the destroy provisioner to wait for relabel+apply to drain the set
  # before attempting the profile delete.
  cmp_list_applied_count_command = local.fleet_enabled ? join(" ", [
    "az fleet clustermeshprofile list-members",
    "--subscription", var.subscription_id,
    "--resource-group", var.resource_group_name,
    "--fleet-name", var.fleet_name,
    "--name", var.cmp_name,
    "--query", "'length(@)'",
    "--output", "tsv",
  ]) : "echo 0"
}

resource "terraform_data" "clustermeshprofile" {
  count = local.fleet_enabled ? 1 : 0

  depends_on = [
    terraform_data.member,
  ]

  input = {
    create_command = local.cmp_create_command
    apply_command  = local.cmp_apply_command
    delete_command = local.cmp_destroy_command
    # `list-members` (default mode) returns members APPLIED to the profile —
    # the same set the profile-delete API checks. We poll its count to know
    # when the relabel+apply reconcile has actually drained membership.
    list_applied_count_command = local.cmp_list_applied_count_command
    # Pre-built per-member `az fleet member update --labels` commands. Joined
    # with newlines and embedded in self.input because destroy provisioners
    # can only access self.input.* (not var.* / local.*).
    member_relabel_commands = local.fleet_enabled ? join("\n", values(local.member_relabel_command)) : ""
  }

  # create + apply are two separate az calls. Use bash with `set -euo pipefail`
  # so any failure aborts the chain.
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = "set -euo pipefail; ${self.input.create_command}; ${self.input.apply_command}"
  }

  # Destroy-time: Fleet's API has a chicken-and-egg between member-delete
  # and clustermeshprofile-delete:
  #   - `az fleet member delete` rejects with `MemberBelongsToClusterMesh`
  #     while the member is still selected by any clustermeshprofile.
  #   - `az fleet clustermeshprofile delete` rejects with
  #     `CannotDeleteClusterMeshProfileWithMembers` while any member is
  #     still in the profile.
  # The az fleet 2.0.4 extension exposes no first-class detach/remove-member
  # command. The way out is to UPDATE each member's labels to a value that
  # the profile selector no longer matches (the profile selects on
  # `${var.member_label_key}=${var.member_label_value}` from create-time),
  # then re-`apply` the profile so it reconciles to an empty member set,
  # then delete the profile. After that the per-member destroy provisioner
  # on terraform_data.member runs successfully (members are no longer
  # attached to any profile).
  #
  # All steps are best-effort (`|| true` / `exit 0` at the end) so a
  # partial-state teardown still progresses to RG cleanup.
  provisioner "local-exec" {
    when        = destroy
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -uo pipefail
      # 1. Relabel every member off the profile's selector. After this, a
      # subsequent `apply` will reconcile the profile's member set to empty.
      printf '%s\n' "${self.input.member_relabel_commands}" | while IFS= read -r cmd; do
        [ -n "$cmd" ] || continue
        echo "[relabel-member] $cmd"
        eval "$cmd" || true
      done

      # 2. Issue an apply to start the reconcile. apply is async on the Fleet
      # RP — `az fleet clustermeshprofile apply` returns when the LRO is
      # accepted, but membership reconciliation (including draining the old
      # applied set) can lag behind by several minutes.
      echo "[apply-profile] ${self.input.apply_command}"
      eval "${self.input.apply_command}" || true

      # 3. Poll the profile's APPLIED member count until it reaches 0. Re-issue
      # `apply` periodically as a nudge in case the first one was a no-op
      # (e.g. Fleet RP hadn't yet observed the relabeled members).
      # Budget: 120 x 5s = 10 min.
      drained=false
      for i in $(seq 1 120); do
        count=$(eval "${self.input.list_applied_count_command}" 2>/dev/null | tr -d '[:space:]')
        echo "[poll-members] attempt $i/120: applied count='$count'"
        if [ "$count" = "0" ]; then
          drained=true
          break
        fi
        # Re-apply every minute (every 12 polls) to push Fleet RP if the
        # initial apply didn't pick up the relabel.
        if [ "$i" -gt 1 ] && [ $((i % 12)) -eq 0 ]; then
          echo "[apply-profile] (nudge) ${self.input.apply_command}"
          eval "${self.input.apply_command}" || true
        fi
        sleep 5
      done
      if [ "$drained" != "true" ]; then
        echo "[poll-members] timed out waiting for applied set to drain; will still attempt delete"
      fi

      # 4. Delete the profile. Brief retry as a backstop in case there's still
      # propagation lag between list-members showing 0 and delete being allowed.
      echo "[delete-profile] ${self.input.delete_command}"
      for i in $(seq 1 30); do
        if eval "${self.input.delete_command}"; then
          echo "[delete-profile] succeeded on attempt $i"
          exit 0
        fi
        if [ "$i" -lt 30 ]; then
          echo "[delete-profile] retry $i/30 in 5s"
          sleep 5
        fi
      done
      echo "[delete-profile] gave up after 30 attempts; downstream cleanup will proceed"
      exit 0
    EOT
  }
}
