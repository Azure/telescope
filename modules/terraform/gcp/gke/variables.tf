variable "gke_config" {
  type = object({
    name        = string
    vpc_name    = string
    subnet_name = string
  })
}
