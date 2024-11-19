variable "json_input" {
  description = "value of the json input"
  type = object({
    project_id = string
    run_id     = string
    region     = string
  })
}

variable "credentials_file" {
  description = "Path to the GCP credentials file"
  type        = string
}
