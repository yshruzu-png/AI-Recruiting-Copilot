#!/usr/bin/env bash
# Build the image and deploy the copilot to Azure Container Apps.
#
#   ./scripts/deploy.sh            # tag = current git commit
#   ./scripts/deploy.sh v1.0       # explicit tag
#
# Prereqs: az login, Weeks 1-5 infrastructure applied, data/extracted/ populated (the image carries the
# synthetic candidate pool). First time only: cd infra && terraform init -upgrade (adds the azuread provider).
#
# To keep the app on later plain `terraform apply` runs, add `deploy_app = true` to infra/terraform.tfvars;
# otherwise the next apply without -var deploy_app=true removes it (handy for saving money).
set -euo pipefail
cd "$(dirname "$0")/.."

TAG="${1:-$(git rev-parse --short HEAD)}"
ls data/extracted/CAND-*.json >/dev/null 2>&1 || { echo "No profiles in data/extracted/. Run scripts/extract_resumes.py first."; exit 1; }

echo "==> 0/3 Resource providers (one-time per subscription; no-op once registered)"
for ns in Microsoft.App Microsoft.ContainerRegistry Microsoft.OperationalInsights; do
  az provider register --namespace "$ns" --wait >/dev/null
done

echo "==> 1/3 Container registry"
(cd infra && terraform apply -auto-approve -var deploy_app=true \
  -target='azurerm_container_registry.acr[0]' -target='azurerm_user_assigned_identity.app[0]')
ACR="$(cd infra && terraform output -raw acr_name)"

echo "==> 2/3 Build recruiting-copilot:${TAG} in ${ACR}"
if ! az acr build --registry "$ACR" --image "recruiting-copilot:${TAG}" --platform linux/amd64 . ; then
  echo "ACR cloud build unavailable on this subscription; building locally with Docker instead."
  az acr login --name "$ACR"
  docker buildx build --platform linux/amd64 -t "${ACR}.azurecr.io/recruiting-copilot:${TAG}" --push .
fi

echo "==> 3/3 Container App, identity roles, Entra ID sign-in"
(cd infra && terraform apply -auto-approve -var deploy_app=true -var image_tag="${TAG}")

URL="$(cd infra && terraform output -raw app_url)"
echo
echo "Deployed: ${URL}"
echo "First request after idle takes ~30s (scale from zero). Health: ${URL}/health"
