output "resource_group" {
  value = azurerm_resource_group.rg.name
}

output "storage_account" {
  value = azurerm_storage_account.st.name
}

output "search_endpoint" {
  value = "https://${azurerm_search_service.search.name}.search.windows.net"
}

output "ai_endpoint" {
  value = azapi_resource.foundry.output.properties.endpoint
}

output "ai_project_endpoint" {
  value = "https://${local.foundry_name}.services.ai.azure.com/api/projects/${local.project_name}"
}

output "chat_deployment" {
  value = azapi_resource.chat.name
}

output "embedding_deployment" {
  value = azapi_resource.embedding.name
}

output "key_vault_uri" {
  value = azurerm_key_vault.kv.vault_uri
}

output "appinsights_connection_string" {
  value     = azurerm_application_insights.appi.connection_string
  sensitive = true
}
