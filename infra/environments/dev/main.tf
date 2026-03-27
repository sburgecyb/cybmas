module "cybmas_dev" {
  source     = "../../"
  project_id = var.project_id
  region     = var.region
  env        = "dev"
}
