scenario_type  = "perf-eval"
scenario_name  = "apiserver-streaming-encoding"
deletion_delay = "3h"
owner          = "aks"

aks_arm_deployment_config_list = [
  {
    name            = "vn10pod10k-streaming-encoding"
    parameters_path = "parameters.json"
  }
]
