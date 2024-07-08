locals {
  role                     = var.agc_config.role
  agc_manager_role         = "AppGw for Containers Configuration Manager"
  network_contributor_role = "Network Contributor"
}

resource "azurerm_application_load_balancer" "agc" {
  name                = var.agc_config.name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags = merge(
    var.tags,
    {
      "role" = local.role
    },
  )
}

resource "azurerm_application_load_balancer_frontend" "frontend" {
  for_each                     = toset(var.agc_config.frontends)
  name                         = each.value
  application_load_balancer_id = azurerm_application_load_balancer.agc.id
  tags                         = var.tags
}

resource "azurerm_application_load_balancer_subnet_association" "association" {
  name                         = "association"
  application_load_balancer_id = azurerm_application_load_balancer.agc.id
  subnet_id                    = var.association_subnet_id
  tags                         = var.tags
}

resource "azurerm_user_assigned_identity" "userassignedidentity" {
  name                = "alb-identity"
  resource_group_name = var.resource_group_name
  location            = var.location
}

resource "azurerm_federated_identity_credential" "federatedidentity" {
  name                = "alb-identity"
  resource_group_name = var.resource_group_name
  parent_id           = azurerm_user_assigned_identity.userassignedidentity.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = var.aks_cluster_oidc_issuer
  subject             = "system:serviceaccount:azure-alb-system:alb-controller-sa"
}

resource "azurerm_role_assignment" "vnetjoin" {
  role_definition_name = local.network_contributor_role
  scope                = var.association_subnet_id
  principal_id         = azurerm_user_assigned_identity.userassignedidentity.principal_id
}

resource "azurerm_role_assignment" "agcconfig" {
  role_definition_name = local.agc_manager_role
  scope                = azurerm_application_load_balancer.agc.id
  principal_id         = azurerm_user_assigned_identity.userassignedidentity.principal_id
}

resource "helm_release" "alb_controller" {
  name       = "alb-controller"
  repository = "oci://mcr.microsoft.com"
  chart      = "application-lb/charts/alb-controller"

  provider = helm

  namespace        = "azure-alb-system"
  create_namespace = true
  version          = "1.0.6"
  values = [
    jsonencode({
      "albController" : {
        "podIdentity" : {
          "clientID" : azurerm_user_assigned_identity.userassignedidentity.client_id
        },
        "env" : [
          {
            "name" : "CUSTOM_LOGGING"
            "value" : "true"
          }
        ]
      }
    })
  ]
}
