data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  suffix       = random_string.suffix.result
  base         = "${var.project_name}-${local.suffix}"
  foundry_name = "aif-${local.base}"
  project_name = "proj-recruiting"
  me           = data.azurerm_client_config.current.object_id
}

# ---------------------------------------------------------------------------
# Resource group
# ---------------------------------------------------------------------------
resource "azurerm_resource_group" "rg" {
  name     = "rg-${var.project_name}"
  location = var.location
  tags     = var.tags
}

# ---------------------------------------------------------------------------
# Observability: Log Analytics + Application Insights
# ---------------------------------------------------------------------------
resource "azurerm_log_analytics_workspace" "law" {
  name                = "log-${local.base}"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

resource "azurerm_application_insights" "appi" {
  name                = "appi-${local.base}"
  location            = var.location
  resource_group_name = azurerm_resource_group.rg.name
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "web"
  tags                = var.tags
}

# ---------------------------------------------------------------------------
# Storage: raw resumes and job descriptions (no shared keys, Entra ID only)
# ---------------------------------------------------------------------------
resource "azurerm_storage_account" "st" {
  name                            = substr("st${var.project_name}${local.suffix}", 0, 24)
  location                        = var.location
  resource_group_name             = azurerm_resource_group.rg.name
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  tags                            = var.tags
}

resource "azurerm_storage_container" "resumes" {
  name                  = "resumes"
  storage_account_id    = azurerm_storage_account.st.id
  container_access_type = "private"
  depends_on            = [azurerm_role_assignment.me_blob]
}

resource "azurerm_storage_container" "jobs" {
  name                  = "job-descriptions"
  storage_account_id    = azurerm_storage_account.st.id
  container_access_type = "private"
  depends_on            = [azurerm_role_assignment.me_blob]
}

# ---------------------------------------------------------------------------
# Azure AI Search (Free tier by default, keys disabled -> RBAC only)
# ---------------------------------------------------------------------------
resource "azurerm_search_service" "search" {
  name                         = "srch-${local.base}"
  location                     = var.location
  resource_group_name          = azurerm_resource_group.rg.name
  sku                          = var.search_sku
  local_authentication_enabled = false
  semantic_search_sku          = var.search_sku == "free" ? null : "free"
  tags                         = var.tags
}

# ---------------------------------------------------------------------------
# Key Vault (RBAC mode) for any secret that can't use managed identity
# ---------------------------------------------------------------------------
resource "azurerm_key_vault" "kv" {
  name                       = substr("kv-${local.base}", 0, 24)
  location                   = var.location
  resource_group_name        = azurerm_resource_group.rg.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  tags                       = var.tags
}

# ---------------------------------------------------------------------------
# Microsoft Foundry: AI Services account + project + model deployments
# (azapi so we can set allowProjectManagement for the new Foundry projects)
# ---------------------------------------------------------------------------
resource "azapi_resource" "foundry" {
  type      = "Microsoft.CognitiveServices/accounts@2025-06-01"
  name      = local.foundry_name
  parent_id = azurerm_resource_group.rg.id
  location  = var.location
  tags      = var.tags

  identity {
    type = "SystemAssigned"
  }

  body = {
    kind = "AIServices"
    sku  = { name = "S0" }
    properties = {
      allowProjectManagement = true
      customSubDomainName    = local.foundry_name
      disableLocalAuth       = true # no API keys - Entra ID only
      publicNetworkAccess    = "Enabled"
    }
  }

  response_export_values = ["properties.endpoint"]
}

resource "azapi_resource" "project" {
  type      = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  name      = local.project_name
  parent_id = azapi_resource.foundry.id
  location  = var.location
  tags      = var.tags

  identity {
    type = "SystemAssigned"
  }

  body = {
    properties = {
      displayName = "AI Recruiting Copilot"
      description = "Portfolio project: resume ingestion, recruiting agent, screening workflow"
    }
  }
}

resource "azapi_resource" "chat" {
  type      = "Microsoft.CognitiveServices/accounts/deployments@2025-06-01"
  name      = var.chat_model_name
  parent_id = azapi_resource.foundry.id

  body = {
    sku = { name = "GlobalStandard", capacity = var.chat_capacity }
    properties = {
      model = {
        format  = "OpenAI"
        name    = var.chat_model_name
        version = var.chat_model_version
      }
    }
  }
}

resource "azapi_resource" "embedding" {
  type      = "Microsoft.CognitiveServices/accounts/deployments@2025-06-01"
  name      = var.embedding_model_name
  parent_id = azapi_resource.foundry.id

  body = {
    sku = { name = "GlobalStandard", capacity = var.embedding_capacity }
    properties = {
      model = {
        format  = "OpenAI"
        name    = var.embedding_model_name
        version = var.embedding_model_version
      }
    }
  }

  # Deployments on the same account must be created one at a time.
  depends_on = [azapi_resource.chat]
}

# ---------------------------------------------------------------------------
# Store the App Insights connection string in Key Vault (shows the pattern;
# the app reads it at runtime with its managed identity)
# ---------------------------------------------------------------------------
resource "time_sleep" "rbac_propagation" {
  create_duration = "60s"
  depends_on      = [azurerm_role_assignment.me_kv]
}

resource "azurerm_key_vault_secret" "appi" {
  name         = "appinsights-connection-string"
  value        = azurerm_application_insights.appi.connection_string
  key_vault_id = azurerm_key_vault.kv.id
  depends_on   = [time_sleep.rbac_propagation]
}

# ---------------------------------------------------------------------------
# Cost guardrail: monthly budget with alerts at 50% / 80% / 100% forecast
# ---------------------------------------------------------------------------
resource "azurerm_consumption_budget_resource_group" "budget" {
  name              = "budget-${var.project_name}"
  resource_group_id = azurerm_resource_group.rg.id
  amount            = var.budget_amount
  time_grain        = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  notification {
    enabled        = true
    threshold      = 50
    operator       = "GreaterThan"
    contact_emails = [var.budget_alert_email]
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    contact_emails = [var.budget_alert_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = [var.budget_alert_email]
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}
