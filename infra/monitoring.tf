# ---------------------------------------------------------------------------
# Week 6: alerting on the guardrail metrics (queries: monitoring/queries.kql)
# ---------------------------------------------------------------------------
resource "azurerm_monitor_action_group" "owner" {
  name                = "ag-${local.base}"
  resource_group_name = azurerm_resource_group.rg.name
  short_name          = "copilot"
  tags                = var.tags

  email_receiver {
    name          = "owner"
    email_address = var.budget_alert_email
  }
}

# A burst of blocked turns means someone is probing the copilot (or a guardrail is misfiring and
# blocking real recruiters). Either way a person should look.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "blocked_turns" {
  name                 = "alert-blocked-turns-${local.base}"
  resource_group_name  = azurerm_resource_group.rg.name
  location             = var.location
  scopes               = [azurerm_application_insights.appi.id]
  description          = "More than ${var.blocked_turns_alert_threshold} guardrail-blocked turns in an hour"
  severity             = 2
  evaluation_frequency = "PT15M"
  window_duration      = "PT1H"
  tags                 = var.tags

  criteria {
    query                   = <<-KQL
      customMetrics
      | where name == "copilot.turns.blocked"
      | summarize blocks = sum(valueSum)
    KQL
    time_aggregation_method = "Total"
    metric_measure_column   = "blocks"
    operator                = "GreaterThan"
    threshold               = var.blocked_turns_alert_threshold

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  auto_mitigation_enabled = true

  action {
    action_groups = [azurerm_monitor_action_group.owner.id]
  }
}
