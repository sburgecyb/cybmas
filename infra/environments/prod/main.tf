module "cybmas_prod" {
  source     = "../../"
  project_id = var.project_id
  region     = var.region
  env        = "prod"
}
