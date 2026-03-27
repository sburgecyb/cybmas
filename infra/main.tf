terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  backend "gcs" {
    # Configured per environment in environments/dev|prod/backend.tf
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "cloud_sql" {
  source  = "./modules/cloud_sql"
  project = var.project_id
  region  = var.region
  env     = var.env
}

module "memorystore" {
  source  = "./modules/memorystore"
  project = var.project_id
  region  = var.region
  env     = var.env
}

module "pubsub" {
  source  = "./modules/pubsub"
  project = var.project_id
  env     = var.env
}

module "cloud_run" {
  source  = "./modules/cloud_run"
  project = var.project_id
  region  = var.region
  env     = var.env
}
