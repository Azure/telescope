variable "json_input" {
  description = "value of the json input for onboarding automation"
  type = object({
    owner                     = string
    run_id                    = string
    scenario_name             = string
    scenario_type             = string
    scenario_version          = string
    resource_group_name       = string
    storage_account_name      = string
    kusto_cluster_name        = string
    kusto_database_name       = string
    kusto_table_name          = string
    create_eventhub_namespace = bool
    eventhub_namespace_name   = optional(string)
    eventhub_instance_name    = optional(string)
    create_eventhub_instance  = bool
    eventgrid_topic_name      = string
    table_creation_script     = string
  })
  default = {
    owner                     = "github_actions"
    run_id                    = "0123456789"
    scenario_name             = "onboarding-new"
    scenario_type             = "issue-repro"
    scenario_version          = "1-0-2"
    resource_group_name       = "sumanth-onboarding-automation"
    storage_account_name      = "sumanthtelescope"
    kusto_cluster_name        = "sumanthtelescope"
    kusto_database_name       = "sumanth-onboarding"
    kusto_table_name          = "onboarding_new_1_0_2"
    create_eventhub_namespace = true
    eventhub_namespace_name   = "sumanthtelescope"
    eventhub_instance_name    = "EH-aks-telescope"
    create_eventhub_instance  = true
    eventgrid_topic_name      = "sumanthtelescope"
    table_creation_script     = "LmNyZWF0ZSB0YWJsZSBbJ29uYm9hcmRpbmdfbmV3XzFfMF8yJ10gKFsndGltZXN0YW1wJ106ZGF0ZXRpbWUsIFsnbWV0cmljJ106c3RyaW5nLCBbJ3RhcmdldF9iYW5kd2lkdGgnXTpsb25nLCBbJ3VuaXQnXTpzdHJpbmcsIFsnaXBlcmZfaW5mbyddOmR5bmFtaWMsIFsnb3NfaW5mbyddOmR5bmFtaWMsIFsnY2xvdWRfaW5mbyddOmR5bmFtaWMsIFsnZWdyZXNzX2lwJ106c3RyaW5nLCBbJ2luZ3Jlc3NfaXAnXTpzdHJpbmcsIFsncnVuX2lkJ106c3RyaW5nLCBbJ3J1bl91cmwnXTpzdHJpbmcpCgouY3JlYXRlIHRhYmxlIFsnb25ib2FyZGluZ19uZXdfMV8wXzInXSBpbmdlc3Rpb24ganNvbiBtYXBwaW5nICdvbmJvYXJkaW5nX25ld18xXzBfMl9tYXBwaW5nJyAnW3siY29sdW1uIjoidGltZXN0YW1wIiwgIlByb3BlcnRpZXMiOnsiUGF0aCI6IiRbXCd0aW1lc3RhbXBcJ10ifX0seyJjb2x1bW4iOiJtZXRyaWMiLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ21ldHJpY1wnXSJ9fSx7ImNvbHVtbiI6InRhcmdldF9iYW5kd2lkdGgiLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ3RhcmdldF9iYW5kd2lkdGhcJ10ifX0seyJjb2x1bW4iOiJ1bml0IiwgIlByb3BlcnRpZXMiOnsiUGF0aCI6IiRbXCd1bml0XCddIn19LHsiY29sdW1uIjoiaXBlcmZfaW5mbyIsICJQcm9wZXJ0aWVzIjp7IlBhdGgiOiIkW1wnaXBlcmZfaW5mb1wnXSJ9fSx7ImNvbHVtbiI6Im9zX2luZm8iLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ29zX2luZm9cJ10ifX0seyJjb2x1bW4iOiJjbG91ZF9pbmZvIiwgIlByb3BlcnRpZXMiOnsiUGF0aCI6IiRbXCdjbG91ZF9pbmZvXCddIn19LHsiY29sdW1uIjoiZWdyZXNzX2lwIiwgIlByb3BlcnRpZXMiOnsiUGF0aCI6IiRbXCdlZ3Jlc3NfaXBcJ10ifX0seyJjb2x1bW4iOiJpbmdyZXNzX2lwIiwgIlByb3BlcnRpZXMiOnsiUGF0aCI6IiRbXCdpbmdyZXNzX2lwXCddIn19LHsiY29sdW1uIjoicnVuX2lkIiwgIlByb3BlcnRpZXMiOnsiUGF0aCI6IiRbXCdydW5faWRcJ10ifX0seyJjb2x1bW4iOiJydW5fdXJsIiwgIlByb3BlcnRpZXMiOnsiUGF0aCI6IiRbXCdydW5fdXJsXCddIn19XSc="
  }
}
