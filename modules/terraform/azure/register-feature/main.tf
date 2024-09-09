locals {
  features_map = { for feature in var.features : "${feature.namespace}-${feature.name}" => feature }
}

# Register features for the Azure provider
resource "azurerm_resource_provider_registration" "register_features" {
  for_each = local.features_map
  name     = each.value.namespace

  feature {
    name       = each.value.name
    registered = true
  }
}

# Use a terraform_data to wait for feature registration
resource "terraform_data" "wait_for_feature" {
  for_each = local.features_map

  provisioner "local-exec" {
    command = <<EOT
      az feature show --namespace "${each.value.namespace}" --name "${each.value.name}" | grep "Registered"
      EOT
  }
  depends_on = [azurerm_resource_provider_registration.register_features]
}

# # Refresh the provider registration if needed
# resource "azurerm_provider" "provider" {
#   for_each = local.features_map

#   namespace  = each.value.namespace
#   depends_on = [terraform_data.wait_for_feature]
# }
