# =============================================================================
# VNet peering submodule — pairwise mesh
#
# Mirrors Step 3b in fleet-setup-script.sh (SHARED_VNET=false mode):
# creates az network vnet peering create in both directions for every ordered
# pair (src, dst) with src != dst, over the VNets in var.vnet_role_to_id.
#
# for_each keys are the stable string "${src_role}->${dst_role}", so adding a
# new cluster role does NOT churn peerings that already exist between other pairs.
# =============================================================================

locals {
  peering_pairs = var.peering_enabled ? {
    for pair in flatten([
      for src_role, src_id in var.vnet_role_to_id : [
        for dst_role, dst_id in var.vnet_role_to_id : {
          key      = "${src_role}->${dst_role}"
          src_role = src_role
          dst_role = dst_role
          src_id   = src_id
          dst_id   = dst_id
          src_name = var.vnet_role_to_name[src_role]
        } if src_role != dst_role
      ]
    ]) : pair.key => pair
  } : {}
}

resource "azurerm_virtual_network_peering" "peering" {
  for_each = local.peering_pairs

  name                         = "${each.value.src_name}-to-${each.value.dst_role}"
  resource_group_name          = var.resource_group_name
  virtual_network_name         = each.value.src_name
  remote_virtual_network_id    = each.value.dst_id
  allow_virtual_network_access = true
  allow_forwarded_traffic      = false
  allow_gateway_transit        = false
  use_remote_gateways          = false
}
