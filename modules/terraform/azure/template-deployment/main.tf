resource "azurerm_template_deployment" "example" {
  name                = var.deployment_name
  resource_group_name = var.resource_group_name
  deployment_mode     = var.deployment_mode

  template_body = file(var.template_file_path)
  parameters    = jsondecode(file(var.parameters_file_path))
}
