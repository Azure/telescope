scenario_type  = "perf-eval"
scenario_name  = "vm-extension"
deletion_delay = "2h"

vm_config_list = [
  {
    info_column_name = "cloud_info.vm_info"
    role             = "vm-role"
    vm_name          = "vm-extension"
    admin_username   = "ubuntu"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  }
]