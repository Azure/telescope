locals {
  role                  = var.appgateway_config.role
  appgateway_name       = var.appgateway_config.appgateway_name
  health_probes         = var.appgateway_config.appgateway_probes
  frontend_ports        = var.appgateway_config.appgateway_frontend_ports
  backend_address_pool  = var.appgateway_config.appgateway_backend_address_pool
  backendhttp_settings  = var.appgateway_config.appgateway_backend_http_settings
  http_listeners        = var.appgateway_config.appgateway_http_listeners
  request_routing_rules = var.appgateway_config.appgateway_request_routing_rules
}

data "azurerm_key_vault" "akstelescope" {
  name                = "akstelescope"
  resource_group_name = "telescope"
}

data "azurerm_key_vault_certificate" "vm-appgateway-vm" {
  name         = "vm-appgateway-vm"
  key_vault_id = data.azurerm_key_vault.akstelescope.id
}

data "azurerm_user_assigned_identity" "telescope_identity" {
  name                = "aks-telescope-operator"
  resource_group_name = "telescope"
}

resource "azurerm_application_gateway" "appgateway" {
  name                = local.appgateway_name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags = merge(
    var.tags,
    {
      "role" = local.role
    },
  )

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 10
  }

  gateway_ip_configuration {
    name      = "my-gateway-ip-configuration"
    subnet_id = var.subnet_id
  }

  dynamic "frontend_port" {
    for_each = local.frontend_ports
    content {
      name = frontend_port.value.name
      port = frontend_port.value.port
    }
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [data.azurerm_user_assigned_identity.telescope_identity.id]
  }

  frontend_ip_configuration {
    name                 = "public"
    public_ip_address_id = var.public_ip_id
  }

  dynamic "backend_address_pool" {
    for_each = local.backend_address_pool
    content {
      name         = backend_address_pool.value.name
      ip_addresses = backend_address_pool.value.ip_addresses
    }
  }

  dynamic "backend_http_settings" {
    for_each = local.backendhttp_settings
    content {
      name                           = backend_http_settings.value.name
      host_name                      = backend_http_settings.value.host_name
      cookie_based_affinity          = backend_http_settings.value.cookie_based_affinity
      port                           = backend_http_settings.value.port
      protocol                       = backend_http_settings.value.protocol
      request_timeout                = backend_http_settings.value.request_timeout
      probe_name                     = backend_http_settings.value.probe_name
      trusted_root_certificate_names = backend_http_settings.value.protocol == "Https" ? ["self-signed-root"] : []
    }
  }

  dynamic "probe" {
    for_each = local.health_probes
    content {
      name                                      = probe.value.name
      protocol                                  = probe.value.protocol
      path                                      = "/"
      pick_host_name_from_backend_http_settings = true
      interval                                  = 10
      timeout                                   = 30
      unhealthy_threshold                       = 3
    }
  }

  ssl_certificate {
    name                = data.azurerm_key_vault_certificate.vm-appgateway-vm.name
    key_vault_secret_id = data.azurerm_key_vault_certificate.vm-appgateway-vm.secret_id
  }

  dynamic "http_listener" {
    for_each = local.http_listeners
    content {
      name                           = http_listener.value.name
      frontend_ip_configuration_name = http_listener.value.frontend_ip_configuration_name
      frontend_port_name             = http_listener.value.frontend_port_name
      protocol                       = http_listener.value.protocol
      host_name                      = http_listener.value.host_name
      ssl_certificate_name           = http_listener.value.protocol == "Https" ? data.azurerm_key_vault_certificate.vm-appgateway-vm.name : ""
    }
  }

  dynamic "request_routing_rule" {
    for_each = local.request_routing_rules
    content {
      name                       = request_routing_rule.value.name
      priority                   = request_routing_rule.value.priority
      rule_type                  = request_routing_rule.value.rule_type
      http_listener_name         = request_routing_rule.value.http_listener_name
      backend_address_pool_name  = request_routing_rule.value.backend_address_pool_name
      backend_http_settings_name = request_routing_rule.value.backend_http_settings_name
    }
  }

  trusted_root_certificate {
    name                = "self-signed-root"
    key_vault_secret_id = data.azurerm_key_vault_certificate.vm-appgateway-vm.secret_id
  }
}
