variable "features" {
  type = list(object({
    namespace = string
    name      = string
  }))
  default = []
}
