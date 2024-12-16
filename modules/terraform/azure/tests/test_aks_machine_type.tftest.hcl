variables {
  scenario_type  = "perf-eval"
  scenario_name  = "my_scenario"
  deletion_delay = "2h"
  owner          = "aks"
  json_input = {
    "run_id" : "123456789",
    "region" : "eastus",
    "public_key_path" : "public_key_path",
    "aks_machine_type" : "Standard_D32s_v4"
  }


  aks_config_list = [
    {
      role        = "test"
      aks_name    = "test"
      dns_prefix  = "test"
      subnet_name = "test-subnet-1"
      sku_tier    = "Standard"
      network_profile = {
        network_plugin      = "azure"
        network_plugin_mode = "overlay"
      }
      default_node_pool = {
        name                         = "default"
        node_count                   = 1
        vm_size                      = "Standard_D32s_v3"
        os_disk_type                 = "Managed"
        only_critical_addons_enabled = false
        temporary_name_for_rotation  = "defaulttmp"
      }
      extra_node_pool = [
        {
          name       = "server"
          node_count = 1
          vm_size    = "Standard_D32s_v3"
          zones      = ["1"]
        },
        {
          name       = "client"
          node_count = 1
          vm_size    = "Standard_L8s_v3"
          zones      = ["1"]
        }
      ]
    }
  ]
}

run "valid_aks_machine_type_override_all" {

  command = plan

  assert {
    condition     = module.aks["test"].aks_cluster.default_node_pool[0].vm_size == var.json_input["aks_machine_type"]
    error_message = "Expected: ${var.json_input["aks_machine_type"]} \n Actual:  ${module.aks["test"].aks_cluster.default_node_pool[0].vm_size}"
  }

  assert {
    condition     = module.aks["test"].aks_cluster_nood_pools["server"].vm_size == var.json_input["aks_machine_type"]
    error_message = "Expected: ${var.json_input["aks_machine_type"]} \n Actual:  ${module.aks["test"].aks_cluster_nood_pools["server"].vm_size}"
  }

  assert {
    condition     = module.aks["test"].aks_cluster_nood_pools["client"].vm_size == var.json_input["aks_machine_type"]
    error_message = "Expected: ${var.json_input["aks_machine_type"]} \n Actual:  ${module.aks["test"].aks_cluster_nood_pools["client"].vm_size}"
  }
}

run "valid_aks_machine_type_no_override" {

  command = plan

  variables {
    json_input = {
      "run_id" : "123456789",
      "region" : "eastus",
      "public_key_path" : "public_key_path",
    }
  }

  assert {
    condition     = module.aks["test"].aks_cluster.default_node_pool[0].vm_size == var.aks_config_list[0].default_node_pool.vm_size
    error_message = "Expected: ${var.aks_config_list[0].default_node_pool.vm_size} \n Actual: ${module.aks["test"].aks_cluster.default_node_pool[0].vm_size}"
  }

  assert {
    condition     = module.aks["test"].aks_cluster_nood_pools["server"].vm_size == var.aks_config_list[0].extra_node_pool[0].vm_size
    error_message = "Expected: ${var.aks_config_list[0].extra_node_pool[0].vm_size} \n Actual:  ${module.aks["test"].aks_cluster_nood_pools["server"].vm_size}"
  }

  assert {
    condition     = module.aks["test"].aks_cluster_nood_pools["client"].vm_size == var.aks_config_list[0].extra_node_pool[1].vm_size
    error_message = "Expected: ${var.aks_config_list[0].extra_node_pool[1].vm_size} \n Actual:  ${module.aks["test"].aks_cluster_nood_pools["client"].vm_size}"
  }
}


