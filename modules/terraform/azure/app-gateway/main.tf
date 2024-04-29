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

resource "azurerm_application_gateway" "appgateway" {
  depends_on          = [azurerm_key_vault_certificate.appgatewayhttps, time_sleep.wait_60_seconds]
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
    content{
      name = frontend_port.value.name
      port = frontend_port.value.port
    }
  }

  ssl_certificate {
    name                = azurerm_key_vault_certificate.appgatewayhttps.name
    key_vault_secret_id = azurerm_key_vault_certificate.appgatewayhttps.secret_id
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
      trusted_root_certificate_names = backend_http_settings.value.protocol == "Https" ? ["self-signed-root"] : []
      probe_name                     = backend_http_settings.value.probe_name
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

  dynamic "http_listener" {
    for_each = local.http_listeners
    content {
      name                           = http_listener.value.name
      frontend_ip_configuration_name = http_listener.value.frontend_ip_configuration_name
      frontend_port_name             = http_listener.value.frontend_port_name
      protocol                       = http_listener.value.protocol
      host_name                      = http_listener.value.host_name
      ssl_certificate_name           = http_listener.value.protocol == "Https" ? azurerm_key_vault_certificate.appgatewayhttps.name : ""
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
    name = "self-signed-root"
    data = "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tDQpNSUlCdHpDQ0FWMENGSEUvNk5mME92L3QxV2JCQlBTOWp2VlBJV0pOTUFvR0NDcUdTTTQ5QkFNQ01GNHhDekFKDQpCZ05WQkFZVEFrNU1NUTR3REFZRFZRUUlEQVZCZW5WeVpURVNNQkFHQTFVRUJ3d0pRVzF6ZEdWeVpHRnRNUkV3DQpEd1lEVlFRS0RBaHViR2xuYUhSbGJqRVlNQllHQTFVRUF3d1BjMlZzWm5OcFoyNWxaQzF5YjI5ME1CNFhEVEl6DQpNRFl5TWpFM05UQXpNMW9YRFRJME1EWXlNVEUzTlRBek0xb3dYakVMTUFrR0ExVUVCaE1DVGt3eERqQU1CZ05WDQpCQWdNQlVGNmRYSmxNUkl3RUFZRFZRUUhEQWxCYlhOMFpYSmtZVzB4RVRBUEJnTlZCQW9NQ0c1c2FXZG9kR1Z1DQpNUmd3RmdZRFZRUUREQTl6Wld4bWMybG5ibVZrTFhKdmIzUXdXVEFUQmdjcWhrak9QUUlCQmdncWhrak9QUU1CDQpCd05DQUFUTzZvVVpsRjBwRWdEME5nQ1Bsc1ptUjk2OVMrcHBzRlF1bVZFK1NYK1JkVDMwZ1BVRjFyRTB1WjZ2DQpLMWJRREhSSVV3bzNnZzJZTnZKb3BvbFVmL3VLTUFvR0NDcUdTTTQ5QkFNQ0EwZ0FNRVVDSVFDbDdlN1o0bHplDQoxTGowMS9zU1I2K0lCZHVESUpNTkQxamdsTTYvdDc0NXh3SWdZSHl3SjArNmw2SHgvT2tOTnlYZmxNalBvaWk0DQpoNHczNzQxNFZqMG56Qk09DQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tDQo="
  }
}

data "azurerm_client_config" "current" {}

resource "time_sleep" "wait_60_seconds" {
  depends_on = [azurerm_key_vault_certificate.appgatewayhttps]

  create_duration = "60s"
}

resource "azurerm_key_vault" "agw" {
  name                = "${var.resource_group_name}-kv"
  location            = var.location
  resource_group_name = var.resource_group_name
  tenant_id           =  data.azurerm_client_config.current.tenant_id
  soft_delete_retention_days = 7
  purge_protection_enabled = false
  sku_name = "standard"
  tags = merge(
    var.tags,
    {
      "role" = local.role
    },
  )
  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    certificate_permissions = [
      "Get", "Create", "List" 
    ]
    secret_permissions = [
      "Get",
    ]
  }
}

resource "azurerm_key_vault_certificate" "appgatewayhttps" {
  name         = "mysite1"
  key_vault_id = azurerm_key_vault.agw.id

  certificate_policy {
    issuer_parameters {
      name = "Self"
    }

    key_properties {
      exportable = true
      key_size   = 2048
      key_type   = "RSA"
      reuse_key  = true
    }

    lifetime_action {
      action {
        action_type = "AutoRenew"
      }

      trigger {
        days_before_expiry = 30
      }
    }

    secret_properties {
      content_type = "application/x-pkcs12"
    }

    x509_certificate_properties {
      # Server Authentication = 1.3.6.1.5.5.7.3.1
      # Client Authentication = 1.3.6.1.5.5.7.3.2
      extended_key_usage = ["1.3.6.1.5.5.7.3.1"]

      key_usage = [
        "cRLSign",
        "dataEncipherment",
        "digitalSignature",
        "keyAgreement",
        "keyCertSign",
        "keyEncipherment",
      ]

      subject_alternative_names {
        dns_names = ["mysite1.com"]
      }

      subject            = "CN=mysite1.com"
      validity_in_months = 12
    }
  }
}