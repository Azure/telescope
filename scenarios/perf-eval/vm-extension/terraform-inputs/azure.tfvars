scenario_type  = "perf-eval"
scenario_name  = "vm-extension"
deletion_delay = "2h"


public_ip_config_list = [
  {
    name = "vm-extension-public-ip-1"
  },
  {
    name = "vm-extension-public-ip-2"
  },
  {
    name = "vm-extension-public-ip-3"
  },
  {
    name = "vm-extension-public-ip-4"
  },
  {
    name = "vm-extension-public-ip-5"
  },
  {
    name = "vm-extension-public-ip-6"
  },
  {
    name = "vm-extension-public-ip-7"
  },
  {
    name = "vm-extension-public-ip-8"
  },
  {
    name = "vm-extension-public-ip-9"
  },
  {
    name = "vm-extension-public-ip-10"
  }
]

network_config_list = [
  {
    role               = "network"
    vnet_name          = "vm-extension-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [
      {
        name           = "vm-extension-subnet"
        address_prefix = "10.1.1.0/24"
      }
    ],
    network_security_group_name = "vm-extension-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "vm-extension-nic-1"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-1"
      },
      {
        nic_name              = "vm-extension-nic-2"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-2"
      },
      {
        nic_name              = "vm-extension-nic-3"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-3"
      },
      {
        nic_name              = "vm-extension-nic-4"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-4"
      },
      {
        nic_name              = "vm-extension-nic-5"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-5"
      },
      {
        nic_name              = "vm-extension-nic-6"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-6"
      },
      {
        nic_name              = "vm-extension-nic-7"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-7"
      },
      {
        nic_name              = "vm-extension-nic-8"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-8"
      },
      {
        nic_name              = "vm-extension-nic-9"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-9"
      },
      {
        nic_name              = "vm-extension-nic-10"
        subnet_name           = "vm-extension-subnet"
        ip_configuration_name = "vm-extension-ip-config"
        public_ip_name        = "vm-extension-public-ip-10"
      }
    ]
    nsr_rules = []
  }
]

vm_config_list = [{
  role           = "vm-role"
  vm_name        = "vm-extension-1"
  nic_name       = "vm-extension-nic-1"
  admin_username = "ubuntu"
  zone           = "1"
  machine_type   = "Standard_D2ds_v5"
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
  },
  {
    role           = "vm-role"
    vm_name        = "vm-extension-2"
    nic_name       = "vm-extension-nic-2"
    admin_username = "ubuntu"
    zone           = "1"
    machine_type   = "Standard_D2ds_v5"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  },
  {
    role           = "vm-role"
    vm_name        = "vm-extension-3"
    nic_name       = "vm-extension-nic-3"
    admin_username = "ubuntu"
    zone           = "1"
    machine_type   = "Standard_D2ds_v5"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  },
  {
    role           = "vm-role"
    vm_name        = "vm-extension-4"
    nic_name       = "vm-extension-nic-4"
    admin_username = "ubuntu"
    zone           = "1"
    machine_type   = "Standard_D2ds_v5"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  },
  {
    role           = "vm-role"
    vm_name        = "vm-extension-5"
    nic_name       = "vm-extension-nic-5"
    admin_username = "ubuntu"
    zone           = "1"
    machine_type   = "Standard_D2ds_v5"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  },
  {
    role           = "vm-role"
    vm_name        = "vm-extension-6"
    nic_name       = "vm-extension-nic-6"
    admin_username = "ubuntu"
    zone           = "1"
    machine_type   = "Standard_D2ds_v5"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  },
  {
    role           = "vm-role"
    vm_name        = "vm-extension-7"
    nic_name       = "vm-extension-nic-7"
    admin_username = "ubuntu"
    zone           = "1"
    machine_type   = "Standard_D2ds_v5"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  },
  {
    role           = "vm-role"
    vm_name        = "vm-extension-8"
    nic_name       = "vm-extension-nic-8"
    admin_username = "ubuntu"
    zone           = "1"
    machine_type   = "Standard_D2ds_v5"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  },
  {
    role           = "vm-role"
    vm_name        = "vm-extension-9"
    nic_name       = "vm-extension-nic-9"
    admin_username = "ubuntu"
    zone           = "1"
    machine_type   = "Standard_D2ds_v5"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
  },
  {
    role           = "vm-role"
    vm_name        = "vm-extension-10"
    nic_name       = "vm-extension-nic-10"
    admin_username = "ubuntu"
    zone           = "1"
    machine_type   = "Standard_D2ds_v5"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
}]