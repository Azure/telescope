locals {  
  role                  = var.appgateway_config.role
  appgateway_name      = var.appgateway_config.appgateway_name  
}

resource "azurerm_application_gateway" "appgateway" {
  name                = local.appgateway_name
  location            = var.location
  resource_group_name = var.resource_group_name

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 10
  }

 gateway_ip_configuration {
    name      = "my-gateway-ip-configuration"
    subnet_id = var.subnet_id
  }
 backend_address_pool {
    name         = "aks-direct"
    ip_addresses = ["10.10.1.7", "10.10.1.8", "10.10.1.9"]
  }

  frontend_ip_configuration {
    name                 = "public"
    public_ip_address_id = var.public_ips[locals.role]
  }

   http_listener {
    name                           = "https-backend-contoso-com-lb"
    frontend_ip_configuration_name = "public"
    frontend_port_name             = "http"
    protocol                       = "Http"
    host_name                      = "https-backend-lb.contoso.com"
  }

  frontend_port {
    name = "http"
    port = 80
  }

backend_http_settings {
    name                           = "aks-https-lb"
    host_name                      = "test.contoso.com"
    cookie_based_affinity          = "Disabled"
    port                           = 443
    protocol                       = "Https"
    request_timeout                = 60
    trusted_root_certificate_names = ["self-signed-root"]
    probe_name                     = "aks-https"
  }

  probe {
    name                                      = "aks-https"
    protocol                                  = "Https"
    path                                      = "/"
    pick_host_name_from_backend_http_settings = true
    interval                                  = 10
    timeout                                   = 30
    unhealthy_threshold                       = 3
  }

  request_routing_rule {
    name                       = "https-backend-contoso-com-lb"
    priority                   = 1000
    rule_type                  = "Basic"
    http_listener_name         = "https-backend-contoso-com-lb"
    backend_address_pool_name  = "aks-lb"
    backend_http_settings_name = "aks-https-lb"
  }



}