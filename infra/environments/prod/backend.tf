terraform {
  backend "gcs" {
    bucket = "cybmas-tf-state-prod"
    prefix = "terraform/state"
  }
}
