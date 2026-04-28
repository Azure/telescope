variable "fleet_enabled" {
  description = "Whether to create the Fleet, members, and clustermeshprofile."
  type        = bool
  default     = false
}

variable "resource_group_name" {
  description = "Resource group that contains the Fleet and the member AKS clusters."
  type        = string
}

variable "location" {
  description = "Azure region for the Fleet resource."
  type        = string
}

variable "subscription_id" {
  description = "Azure subscription GUID (used to construct AKS resource IDs and CLI calls)."
  type        = string
}

variable "fleet_name" {
  description = "Name of the Azure Fleet Manager resource."
  type        = string
}

variable "cmp_name" {
  description = "Name of the Fleet ClusterMesh Profile."
  type        = string
}

variable "member_label_key" {
  description = "Label key set on fleet members and used as the clustermeshprofile selector."
  type        = string
  default     = "mesh"
}

variable "member_label_value" {
  description = "Label value set on fleet members and used as the clustermeshprofile selector."
  type        = string
  default     = "true"
}

variable "members" {
  description = "List of fleet members. aks_name identifies the AKS cluster in the same resource group; member_name is the Fleet-side name (intentionally may differ from aks_name)."
  type = list(object({
    member_name = string
    aks_name    = string
  }))
  default = []
}

variable "tags" {
  description = "Tags applied to the Fleet resource."
  type        = map(string)
  default     = {}
}
