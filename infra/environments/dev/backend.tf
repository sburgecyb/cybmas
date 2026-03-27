terraform {
  backend "gcs" {
    bucket = "cybmas-tf-state-dev"
    prefix = "terraform/state"
  }
}
