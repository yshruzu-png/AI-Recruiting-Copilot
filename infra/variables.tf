variable "subscription_id" {
  description = "Azure subscription ID (az account show --query id -o tsv)"
  type        = string
}

variable "location" {
  description = "Region. Must support Content Understanding and your chosen models (swedencentral, westus, australiaeast are safe picks)."
  type        = string
  default     = "swedencentral"
}

variable "project_name" {
  description = "Short name used in resource names (lowercase letters/numbers)"
  type        = string
  default     = "recruitcopilot"
}

variable "search_sku" {
  description = "AI Search tier. 'free' costs nothing (1 per subscription, no semantic ranker). 'basic' adds semantic ranker (~USD 75/month)."
  type        = string
  default     = "free"
}

variable "chat_model_name" {
  description = "Chat + vision model. Check the Foundry model catalog for what is current in your region."
  type        = string
  default     = "gpt-4.1-mini"
}

variable "chat_model_version" {
  type    = string
  default = "2025-04-14"
}

variable "chat_capacity" {
  description = "Thousands of tokens per minute"
  type        = number
  default     = 30
}

variable "embedding_model_name" {
  type    = string
  default = "text-embedding-3-small"
}

variable "embedding_model_version" {
  type    = string
  default = "1"
}

variable "embedding_capacity" {
  type    = number
  default = 30
}

variable "budget_amount" {
  description = "Monthly budget for the resource group (in your billing currency)"
  type        = number
  default     = 20
}

variable "budget_alert_email" {
  description = "Email that receives budget alerts"
  type        = string
}

variable "tags" {
  type = map(string)
  default = {
    project = "ai-recruiting-copilot"
    purpose = "portfolio"
  }
}

variable "content_filter_threshold" {
  description = "Severity at which the chat deployment blocks hate / sexual / violence / self-harm content: Low, Medium or High"
  type        = string
  default     = "Medium"
  validation {
    condition     = contains(["Low", "Medium", "High"], var.content_filter_threshold)
    error_message = "Use Low, Medium or High."
  }
}

variable "blocked_turns_alert_threshold" {
  description = "Email an alert when more than this many turns are blocked by guardrails in one hour"
  type        = number
  default     = 10
}

variable "deploy_app" {
  description = "Deploy the API to Container Apps (registry + app). scripts/deploy.sh sets this."
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Tag of the recruiting-copilot image in the registry"
  type        = string
  default     = "latest"
}

variable "enable_auth" {
  description = "Require Entra ID sign-in in front of the deployed app"
  type        = bool
  default     = true
}

variable "github_repository" {
  description = "owner/repo allowed to run the live evaluation workflow with OIDC; empty = no CI identity"
  type        = string
  default     = ""
}
