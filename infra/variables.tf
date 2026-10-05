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
