resource "azurerm_resource_group_template_deployment" "template_deployment" {
  count               = var.parameters_path == null ? 0 : 1
  name                = var.deployment_name
  resource_group_name = var.resource_group_name
  deployment_mode     = "Incremental"

  template_content = file("${path.module}/template.json")
  parameters_content = templatefile(var.parameters_path, {
    location          = var.location
    owner             = var.tags["owner"]
    scenario          = var.tags["scenario"]
    deletion_due_time = var.tags["deletion_due_time"]
    run_id            = var.tags["run_id"]
  })
}
