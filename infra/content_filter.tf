# ---------------------------------------------------------------------------
# Week 5: content filter (Responsible AI policy) on the chat deployment
#
# The platform layer of the guardrails. Azure checks every prompt and completion on the server side,
# before the app's own checks in src/copilot/guardrails.py:
# - Prompt Shields for jailbreaks (user prompt) and indirect attacks (instructions hidden in
#   documents, e.g. a resume that talks to the AI screener)
# - harm categories on both prompt and completion
# - protected material on completions
# ---------------------------------------------------------------------------
locals {
  harm_filters = flatten([
    for category in ["Hate", "Sexual", "Violence", "Selfharm"] : [
      for source in ["Prompt", "Completion"] : {
        name              = category
        source            = source
        enabled           = true
        blocking          = true
        severityThreshold = var.content_filter_threshold
      }
    ]
  ])
  shield_filters = [
    { name = "Jailbreak", source = "Prompt", enabled = true, blocking = true },
    { name = "Indirect Attack", source = "Prompt", enabled = true, blocking = true },
    { name = "Protected Material Text", source = "Completion", enabled = true, blocking = true },
    { name = "Protected Material Code", source = "Completion", enabled = true, blocking = false }, # annotate only
  ]
}

resource "azapi_resource" "content_filter" {
  type      = "Microsoft.CognitiveServices/accounts/raiPolicies@2024-10-01"
  name      = "recruiting-copilot-guardrails"
  parent_id = azapi_resource.foundry.id

  body = {
    properties = {
      basePolicyName = "Microsoft.DefaultV2"
      mode           = "Blocking"
      contentFilters = concat(local.harm_filters, local.shield_filters)
    }
  }
}
