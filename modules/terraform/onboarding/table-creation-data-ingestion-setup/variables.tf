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
    data_connection_name      = string
    create_eventhub_namespace = bool
    eventhub_namespace_name   = optional(string)
    table_creation_script     = string
  })
  default = {
    owner                     = "schinnapulla"
    run_id                    = "08062024"
    scenario_name             = "vm-vm-iperf"
    scenario_type             = "perf-eval"
    scenario_version          = "v1.2.2"
    resource_group_name       = "schinnapulla"
    storage_account_name      = "schinnapulla"
    kusto_cluster_name        = "schinnapulla"
    kusto_database_name       = "perf-eval"
    kusto_table_name          = "vm_vm_iperf_v1_2_2"
    data_connection_name      = "vm-vm-iperf-v1.2.2"
    create_eventhub_namespace = false
    eventhub_namespace_name   = "ADX-EG-akstelescope-08-06-2024-16-56-33"
    table_creation_script     = "LmNyZWF0ZSB0YWJsZSBbJ3ZtX3ZtX2lwZXJmX3YxXzJfMiddIChbJ3RpbWVzdGFtcCddOmRhdGV0aW1lLCBbJ21ldHJpYyddOnN0cmluZywgWyd0YXJnZXRfYmFuZHdpZHRoJ106cmVhbCwgWyd1bml0J106c3RyaW5nLCBbJ2lwZXJmX2luZm8nXTpkeW5hbWljLCBbJ2Nsb3VkX2luZm8nXTpkeW5hbWljLCBbJ2VncmVzc19pcCddOnN0cmluZywgWydpbmdyZXNzX2lwJ106c3RyaW5nLCBbJ3J1bl9pZCddOnN0cmluZywgWydydW5fdXJsJ106c3RyaW5nLCBbJ2RhdGFwYXRoJ106c3RyaW5nKQoKLmNyZWF0ZSB0YWJsZSBbJ3ZtX3ZtX2lwZXJmX3YxXzJfMiddIGluZ2VzdGlvbiBqc29uIG1hcHBpbmcgJ3ZtX3ZtX2lwZXJmX3YxXzJfMl9tYXBwaW5nJyAnW3siY29sdW1uIjoidGltZXN0YW1wIiwgIlByb3BlcnRpZXMiOnsiUGF0aCI6IiRbXCd0aW1lc3RhbXBcJ10ifX0seyJjb2x1bW4iOiJtZXRyaWMiLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ21ldHJpY1wnXSJ9fSx7ImNvbHVtbiI6InRhcmdldF9iYW5kd2lkdGgiLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ3RhcmdldF9iYW5kd2lkdGhcJ10ifX0seyJjb2x1bW4iOiJ1bml0IiwgIlByb3BlcnRpZXMiOnsiUGF0aCI6IiRbXCd1bml0XCddIn19LHsiY29sdW1uIjoiaXBlcmZfaW5mbyIsICJQcm9wZXJ0aWVzIjp7IlBhdGgiOiIkW1wnaXBlcmZfaW5mb1wnXSJ9fSx7ImNvbHVtbiI6ImNsb3VkX2luZm8iLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ2Nsb3VkX2luZm9cJ10ifX0seyJjb2x1bW4iOiJlZ3Jlc3NfaXAiLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ2VncmVzc19pcFwnXSJ9fSx7ImNvbHVtbiI6ImluZ3Jlc3NfaXAiLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ2luZ3Jlc3NfaXBcJ10ifX0seyJjb2x1bW4iOiJydW5faWQiLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ3J1bl9pZFwnXSJ9fSx7ImNvbHVtbiI6InJ1bl91cmwiLCAiUHJvcGVydGllcyI6eyJQYXRoIjoiJFtcJ3J1bl91cmxcJ10ifX0seyJjb2x1bW4iOiJkYXRhcGF0aCIsICJQcm9wZXJ0aWVzIjp7IlBhdGgiOiIkW1wnZGF0YXBhdGhcJ10ifX1dJw=="
  }
}
