#!/usr/bin/env bash
# Writes .env at the repo root from Terraform outputs.
set -euo pipefail
cd "$(dirname "$0")/../infra"

out() { terraform output -raw "$1"; }

cat > ../.env <<EOF
AZURE_RESOURCE_GROUP=$(out resource_group)
AZURE_STORAGE_ACCOUNT=$(out storage_account)
AZURE_SEARCH_ENDPOINT=$(out search_endpoint)
AZURE_AI_ENDPOINT=$(out ai_endpoint)
AZURE_AI_PROJECT_ENDPOINT=$(out ai_project_endpoint)
AZURE_CHAT_DEPLOYMENT=$(out chat_deployment)
AZURE_EMBEDDING_DEPLOYMENT=$(out embedding_deployment)
AZURE_KEY_VAULT_URI=$(out key_vault_uri)
APPLICATIONINSIGHTS_CONNECTION_STRING=$(out appinsights_connection_string)
EOF

echo "Wrote $(cd .. && pwd)/.env"
