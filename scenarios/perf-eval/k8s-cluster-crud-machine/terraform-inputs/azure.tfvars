scenario_type  = "perf-eval"
scenario_name  = "k8s-cluster-crud-machine"
deletion_delay = "2h"
owner          = "aks"

# AKS Machine API CRUD scenario.
#
# The cluster is provisioned with `default_node_pool = null` because the
# Machine API requires the user-mode agent pool to be created with
# `mode = Machines` via the ARM PUT call performed at test time by
# `modules/python/crud/main.py create-machine`. Terraform only owns the
# cluster shell; the system pool is injected at job runtime via the
# `SYSTEM_NODE_POOL` matrix variable (see
# `steps/terraform/set-input-variables-azure.yml`), and the
# machine-mode user pool is born during the `create-machine` step.
aks_cli_config_list = [
  {
    role                          = "client"
    aks_name                      = "mchapi"
    sku_tier                      = "standard"
    use_aks_preview_cli_extension = true
    default_node_pool             = null

    optional_parameters = [
      { name = "network-plugin", value = "azure" },
      { name = "network-plugin-mode", value = "overlay" }
    ]
  }
]
