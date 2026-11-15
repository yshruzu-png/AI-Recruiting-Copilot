# ---------------------------------------------------------------------------
# Week 6: deploy the API + chat page to Azure Container Apps
#
# Off by default (deploy_app = false), so `terraform apply` for development never starts paying for
# a registry or a running app. scripts/deploy.sh turns it on and builds the image.
#
#   Container Registry (no admin user) --AcrPull--> user-assigned identity <-- Container App
#   Identity roles: Foundry (models, Content Understanding, Prompt Shields), Search (read), Key Vault (read)
#   Entra ID sign-in in front of the app (Container Apps authentication), /health left open for probes
# ---------------------------------------------------------------------------
locals {
  app_count  = var.deploy_app ? 1 : 0
  auth_count = var.deploy_app && var.enable_auth ? 1 : 0
  acr_name   = substr(replace("acr${local.base}", "-", ""), 0, 50)
}

resource "azurerm_container_registry" "acr" {
  count               = local.app_count
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false # pulls use the app's managed identity
  tags                = var.tags
}

resource "azurerm_user_assigned_identity" "app" {
  count               = local.app_count
  name                = "id-app-${local.base}"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  tags                = var.tags
}

# --- Least-privilege roles for the app identity ----------------------------
resource "azurerm_role_assignment" "app_acr_pull" {
  count                = local.app_count
  scope                = azurerm_container_registry.acr[0].id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app[0].principal_id
}

resource "azurerm_role_assignment" "app_ai_developer" {
  count              = local.app_count
  scope              = azapi_resource.foundry.id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/64702f94-c441-49e6-a78b-ef80e0188fee" # Azure AI Developer
  principal_id       = azurerm_user_assigned_identity.app[0].principal_id
}

resource "azurerm_role_assignment" "app_cog_user" {
  count                = local.app_count
  scope                = azapi_resource.foundry.id
  role_definition_name = "Cognitive Services User" # model calls, Prompt Shields
  principal_id         = azurerm_user_assigned_identity.app[0].principal_id
}

resource "azurerm_role_assignment" "app_search_reader" {
  count                = local.app_count
  scope                = azurerm_search_service.search.id
  role_definition_name = "Search Index Data Reader" # read-only: the app never changes the index
  principal_id         = azurerm_user_assigned_identity.app[0].principal_id
}

resource "azurerm_role_assignment" "app_kv_reader" {
  count                = local.app_count
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app[0].principal_id
}

resource "time_sleep" "app_rbac" {
  count           = local.app_count
  create_duration = "60s"
  depends_on = [azurerm_role_assignment.app_acr_pull, azurerm_role_assignment.app_ai_developer,
  azurerm_role_assignment.app_cog_user, azurerm_role_assignment.app_search_reader, azurerm_role_assignment.app_kv_reader]
}

# --- Container Apps ---------------------------------------------------------
resource "azurerm_container_app_environment" "env" {
  count                      = local.app_count
  name                       = "cae-${local.base}"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  tags                       = var.tags
}

resource "azurerm_container_app" "app" {
  count                        = local.app_count
  name                         = "ca-${local.base}"
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.env[0].id
  revision_mode                = "Single"
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app[0].id]
  }

  registry {
    server   = azurerm_container_registry.acr[0].login_server
    identity = azurerm_user_assigned_identity.app[0].id
  }

  # Pulled from Key Vault by the identity at startup; never in Terraform variables or the image.
  secret {
    name                = "appinsights-connection-string"
    key_vault_secret_id = azurerm_key_vault_secret.appi.versionless_id
    identity            = azurerm_user_assigned_identity.app[0].id
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # Scale to zero when idle (pay nothing); one replica max because chat sessions live in memory.
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "copilot"
      image  = "${azurerm_container_registry.acr[0].login_server}/recruiting-copilot:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "AZURE_CLIENT_ID" # tells DefaultAzureCredential which managed identity to use
        value = azurerm_user_assigned_identity.app[0].client_id
      }
      env {
        name  = "AZURE_AI_ENDPOINT"
        value = azapi_resource.foundry.output.properties.endpoint
      }
      env {
        name  = "AZURE_AI_PROJECT_ENDPOINT"
        value = "https://${local.foundry_name}.services.ai.azure.com/api/projects/${local.project_name}"
      }
      env {
        name  = "AZURE_SEARCH_ENDPOINT"
        value = "https://${azurerm_search_service.search.name}.search.windows.net"
      }
      env {
        name  = "AZURE_CHAT_DEPLOYMENT"
        value = azapi_resource.chat.name
      }
      env {
        name  = "AZURE_EMBEDDING_DEPLOYMENT"
        value = azapi_resource.embedding.name
      }
      env {
        name  = "REQUIRE_AUTH" # the app refuses unauthenticated calls even if sign-in is ever switched off
        value = var.enable_auth ? "true" : "false"
      }
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-connection-string"
      }

      liveness_probe {
        transport        = "HTTP"
        path             = "/health"
        port             = 8000
        initial_delay    = 10
        interval_seconds = 30
      }
    }
  }

  depends_on = [time_sleep.app_rbac]
}

# --- Entra ID sign-in (Container Apps authentication) ------------------------
data "azuread_client_config" "current" {}

resource "azuread_application" "web" {
  count            = local.auth_count
  display_name     = "AI Recruiting Copilot (${local.base})"
  sign_in_audience = "AzureADMyOrg" # only accounts in your tenant
  owners           = [data.azuread_client_config.current.object_id]

  web {
    implicit_grant {
      id_token_issuance_enabled = true # sign-in only; the app calls no APIs on the user's behalf
    }
  }

  lifecycle {
    ignore_changes = [web[0].redirect_uris] # managed by azuread_application_redirect_uris below
  }
}

resource "azuread_service_principal" "web" {
  count     = local.auth_count
  client_id = azuread_application.web[0].client_id
  owners    = [data.azuread_client_config.current.object_id]
}

# Set after the app exists, because the callback URL needs the app's address.
resource "azuread_application_redirect_uris" "web" {
  count          = local.auth_count
  application_id = azuread_application.web[0].id
  type           = "Web"
  redirect_uris  = ["https://${azurerm_container_app.app[0].ingress[0].fqdn}/.auth/login/aad/callback"]
}

resource "azapi_resource" "app_auth" {
  count     = local.auth_count
  type      = "Microsoft.App/containerApps/authConfigs@2024-03-01"
  name      = "current"
  parent_id = azurerm_container_app.app[0].id

  body = {
    properties = {
      platform = { enabled = true }
      globalValidation = {
        unauthenticatedClientAction = "RedirectToLoginPage"
        redirectToProvider          = "azureactivedirectory"
        excludedPaths               = ["/health"]
      }
      identityProviders = {
        azureActiveDirectory = {
          enabled = true
          registration = {
            clientId     = azuread_application.web[0].client_id
            openIdIssuer = "https://login.microsoftonline.com/${data.azuread_client_config.current.tenant_id}/v2.0"
          }
          validation = {
            allowedAudiences = [azuread_application.web[0].client_id]
          }
        }
      }
      login = { tokenStore = { enabled = false } }
    }
  }
}
