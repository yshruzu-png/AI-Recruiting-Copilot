# ---------------------------------------------------------------------------
# Week 6: identity for the live-evaluation GitHub Actions workflow (.github/workflows/eval-live.yml)
#
# GitHub signs in with OpenID Connect: a federated credential trusts tokens GitHub issues for this
# repository's "azure-live" environment. No client secret exists anywhere.
# Created only when github_repository is set, e.g. github_repository = "yshruzu-png/AI-Recruiting-Copilot".
# ---------------------------------------------------------------------------
locals {
  ci_count = var.github_repository == "" ? 0 : 1
}

resource "azuread_application" "ci" {
  count        = local.ci_count
  display_name = "AI Recruiting Copilot CI (${local.base})"
  owners       = [data.azuread_client_config.current.object_id]
}

resource "azuread_service_principal" "ci" {
  count     = local.ci_count
  client_id = azuread_application.ci[0].client_id
  owners    = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_federated_identity_credential" "ci" {
  count          = local.ci_count
  application_id = azuread_application.ci[0].id
  display_name   = "github-azure-live"
  description    = "GitHub Actions, environment azure-live"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repository}:environment:azure-live"
}

# Read-only data access plus model calls: enough to run the evaluations, not to change infrastructure.
resource "azurerm_role_assignment" "ci_cog_user" {
  count                = local.ci_count
  scope                = azapi_resource.foundry.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azuread_service_principal.ci[0].object_id
}

resource "azurerm_role_assignment" "ci_ai_developer" {
  count              = local.ci_count
  scope              = azapi_resource.foundry.id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/64702f94-c441-49e6-a78b-ef80e0188fee"
  principal_id       = azuread_service_principal.ci[0].object_id
}

resource "azurerm_role_assignment" "ci_search_reader" {
  count                = local.ci_count
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Index Data Reader"
  principal_id         = azuread_service_principal.ci[0].object_id
}

resource "azurerm_role_assignment" "ci_blob_reader" {
  count                = local.ci_count
  scope                = azurerm_storage_account.st.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azuread_service_principal.ci[0].object_id
}
