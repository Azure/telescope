scenario_type  = "perf-eval"
scenario_name  = "ccp-provisioning-H2"
deletion_delay = "2h"
owner          = "aks"

aks_cli_config_list = [
  {
    role               = "client"
    aks_name           = "ccp-provisioning-H2"
    sku_tier           = "standard"
    kubernetes_version = "1.33"
    use_az_rest        = true
    rest_call_config = {
      method         = "PUT"
      api_version    = "2026-01-02-preview"
      body_json_path = "../../../scenarios/perf-eval/ccp-provisioning/config/aks-rest-body-H2.json"
    }
  }
]
