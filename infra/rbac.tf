# Every service has keys disabled, so access is granted with Azure RBAC.
# "me" = whoever runs terraform apply (you, via az login).

# --- You (developer) -------------------------------------------------------
resource "azurerm_role_assignment" "me_blob" {
  scope                = azurerm_storage_account.st.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = local.me
}

resource "azurerm_role_assignment" "me_search_data" {
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = local.me
}

resource "azurerm_role_assignment" "me_search_service" {
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Service Contributor"
  principal_id         = local.me
}

resource "azurerm_role_assignment" "me_ai_user" {
  scope                = azapi_resource.foundry.id
  role_definition_name = "Azure AI User"
  principal_id         = local.me
}

resource "azurerm_role_assignment" "me_cog_user" {
  scope                = azapi_resource.foundry.id
  role_definition_name = "Cognitive Services User"
  principal_id         = local.me
}

resource "azurerm_role_assignment" "me_kv" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = local.me
}

# --- Foundry account managed identity (used by Content Understanding / agents later)
resource "azurerm_role_assignment" "foundry_blob_reader" {
  scope                = azurerm_storage_account.st.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azapi_resource.foundry.identity[0].principal_id
}

resource "azurerm_role_assignment" "foundry_search_reader" {
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Index Data Reader"
  principal_id         = azapi_resource.foundry.identity[0].principal_id
}
