scenario_type  = "perf-eval"
scenario_name  = "vm-run-command"
deletion_delay = "2h"


public_ip_config_list = [
  {
    name = "vm-run-command-public-ip-1"
  },
  {
    name = "vm-run-command-public-ip-2"
  },
  {
    name = "vm-run-command-public-ip-3"
  },
  {
    name = "vm-run-command-public-ip-4"
  },
  {
    name = "vm-run-command-public-ip-5"
  },
  {
    name = "vm-run-command-public-ip-6"
  },
  {
    name = "vm-run-command-public-ip-7"
  },
  {
    name = "vm-run-command-public-ip-8"
  },
  {
    name = "vm-run-command-public-ip-9"
  },
  {
    name = "vm-run-command-public-ip-10"
  }
]

network_config_list = [
  {
    role               = "network"
    vnet_name          = "vm-run-command-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [
      {
        name           = "vm-run-command-subnet"
        address_prefix = "10.1.1.0/24"
      }
    ],
    network_security_group_name = "vm-run-command-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "vm-run-command-nic-1"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-1"
      },
      {
        nic_name              = "vm-run-command-nic-2"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-2"
      },
      {
        nic_name              = "vm-run-command-nic-3"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-3"
      },
      {
        nic_name              = "vm-run-command-nic-4"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-4"
      },
      {
        nic_name              = "vm-run-command-nic-5"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-5"
      },
      {
        nic_name              = "vm-run-command-nic-6"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-6"
      },
      {
        nic_name              = "vm-run-command-nic-7"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-7"
      },
      {
        nic_name              = "vm-run-command-nic-8"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-8"
      },
      {
        nic_name              = "vm-run-command-nic-9"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-9"
      },
      {
        nic_name              = "vm-run-command-nic-10"
        subnet_name           = "vm-run-command-subnet"
        ip_configuration_name = "vm-run-command-ip-config"
        public_ip_name        = "vm-run-command-public-ip-10"
      }
    ]
    nsr_rules = []
  }
]

vm_config_list = [{
  role           = "vm-role"
  vm_name        = "vm-run-command-1"
  nic_name       = "vm-run-command-nic-1"
  admin_username = "ubuntu"
  zone           = "1"
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
    vm_name        = "vm-run-command-2"
    nic_name       = "vm-run-command-nic-2"
    admin_username = "ubuntu"
    zone           = "1"
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
    vm_name        = "vm-run-command-3"
    nic_name       = "vm-run-command-nic-3"
    admin_username = "ubuntu"
    zone           = "1"
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
    vm_name        = "vm-run-command-4"
    nic_name       = "vm-run-command-nic-4"
    admin_username = "ubuntu"
    zone           = "1"
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
    vm_name        = "vm-run-command-5"
    nic_name       = "vm-run-command-nic-5"
    admin_username = "ubuntu"
    zone           = "1"
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
    vm_name        = "vm-run-command-6"
    nic_name       = "vm-run-command-nic-6"
    admin_username = "ubuntu"
    zone           = "1"
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
    vm_name        = "vm-run-command-7"
    nic_name       = "vm-run-command-nic-7"
    admin_username = "ubuntu"
    zone           = "1"
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
    vm_name        = "vm-run-command-8"
    nic_name       = "vm-run-command-nic-8"
    admin_username = "ubuntu"
    zone           = "1"
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
    vm_name        = "vm-run-command-9"
    nic_name       = "vm-run-command-nic-9"
    admin_username = "ubuntu"
    zone           = "1"
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
    vm_name        = "vm-run-command-10"
    nic_name       = "vm-run-command-nic-10"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = false
}]