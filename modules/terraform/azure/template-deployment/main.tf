resource "azurerm_template_deployment" "example" {
  name                = "example-deployment"
  resource_group_name = azurerm_resource_group.example.name
  deployment_mode     = "Incremental"

  template_body      = file("template.json")
  parameters_content = file("parameters.json")
}
