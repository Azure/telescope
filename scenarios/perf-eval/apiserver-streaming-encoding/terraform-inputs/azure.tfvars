scenario_type  = "perf-eval"
scenario_name  = "apiserver-streaming-encoding"
deletion_delay = "3h"
owner          = "aks"

aks_arm_deployment_config_list = [
  {
    name            = "vn10pod100-custom-image"
    parameters_path = "parameters.json"
  }
]
