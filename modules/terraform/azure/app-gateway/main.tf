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

  frontend_port {
    name = "http"
    port = 80
  }
 frontend_ip_configuration {
    name                 = "public"
    public_ip_address_id = var.public_ip_id
  }

 backend_address_pool {
    name         = "aks-direct"
    ip_addresses = ["10.10.1.7", "10.10.1.8", "10.10.1.9"]
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

   http_listener {
    name                           = "https-backend-contoso-com-lb"
    frontend_ip_configuration_name = "public"
    frontend_port_name             = "http"
    protocol                       = "Http"
    host_name                      = "https-backend-lb.contoso.com"
  }

  request_routing_rule {
    name                       = "https-backend-contoso-com-lb"
    priority                   = 1000
    rule_type                  = "Basic"
    http_listener_name         = "https-backend-contoso-com-lb"
    backend_address_pool_name  = "aks-lb"
    backend_http_settings_name = "aks-https-lb"
  }

trusted_root_certificate {
    name = "self-signed-root"
    data = "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tDQpNSUlCdHpDQ0FWMENGSEUvNk5mME92L3QxV2JCQlBTOWp2VlBJV0pOTUFvR0NDcUdTTTQ5QkFNQ01GNHhDekFKDQpCZ05WQkFZVEFrNU1NUTR3REFZRFZRUUlEQVZCZW5WeVpURVNNQkFHQTFVRUJ3d0pRVzF6ZEdWeVpHRnRNUkV3DQpEd1lEVlFRS0RBaHViR2xuYUhSbGJqRVlNQllHQTFVRUF3d1BjMlZzWm5OcFoyNWxaQzF5YjI5ME1CNFhEVEl6DQpNRFl5TWpFM05UQXpNMW9YRFRJME1EWXlNVEUzTlRBek0xb3dYakVMTUFrR0ExVUVCaE1DVGt3eERqQU1CZ05WDQpCQWdNQlVGNmRYSmxNUkl3RUFZRFZRUUhEQWxCYlhOMFpYSmtZVzB4RVRBUEJnTlZCQW9NQ0c1c2FXZG9kR1Z1DQpNUmd3RmdZRFZRUUREQTl6Wld4bWMybG5ibVZrTFhKdmIzUXdXVEFUQmdjcWhrak9QUUlCQmdncWhrak9QUU1CDQpCd05DQUFUTzZvVVpsRjBwRWdEME5nQ1Bsc1ptUjk2OVMrcHBzRlF1bVZFK1NYK1JkVDMwZ1BVRjFyRTB1WjZ2DQpLMWJRREhSSVV3bzNnZzJZTnZKb3BvbFVmL3VLTUFvR0NDcUdTTTQ5QkFNQ0EwZ0FNRVVDSVFDbDdlN1o0bHplDQoxTGowMS9zU1I2K0lCZHVESUpNTkQxamdsTTYvdDc0NXh3SWdZSHl3SjArNmw2SHgvT2tOTnlYZmxNalBvaWk0DQpoNHczNzQxNFZqMG56Qk09DQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tDQo="
  }

}