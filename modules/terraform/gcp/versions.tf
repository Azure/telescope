terraform {
  required_version = ">=1.5.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.12.0"
    }
  }
}


provider "google" {
  project = local.project_id
  region  = local.region
}
