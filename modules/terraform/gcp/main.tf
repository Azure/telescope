locals {
  project_id = lookup(var.json_input, "project_id", null)
  region     = lookup(var.json_input, "region", "us-central1")
  run_id     = lookup(var.json_input, "run_id", "123456")
}
