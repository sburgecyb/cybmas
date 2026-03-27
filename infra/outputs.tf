output "api_gateway_url" {
  description = "Cloud Run URL for the API Gateway service"
  value       = module.cloud_run.api_gateway_url
}

output "orchestrator_url" {
  description = "Cloud Run URL for the Orchestrator service"
  value       = module.cloud_run.orchestrator_url
}

output "database_connection_name" {
  description = "Cloud SQL connection name"
  value       = module.cloud_sql.connection_name
}
