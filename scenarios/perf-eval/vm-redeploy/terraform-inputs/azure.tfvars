scenario_type  = "perf-eval"
scenario_name  = "vm-redeploy"
deletion_delay = "2h"
public_ip_config_list = [
  {
    name = "vm-redeploy-public-ip-1"
  },
  {
    name = "vm-redeploy-public-ip-2"
  },
  {
    name = "vm-redeploy-public-ip-3"
  },
  {
    name = "vm-redeploy-public-ip-4"
  },
  {
    name = "vm-redeploy-public-ip-5"
  },
  {
    name = "vm-redeploy-public-ip-6"
  },
  {
    name = "vm-redeploy-public-ip-7"
  },
  {
    name = "vm-redeploy-public-ip-8"
  },
  {
    name = "vm-redeploy-public-ip-9"
  },
  {
    name = "vm-redeploy-public-ip-10"
  },
  {
    name = "vm-redeploy-public-ip-11"
  },
  {
    name = "vm-redeploy-public-ip-12"
  },
  {
    name = "vm-redeploy-public-ip-13"
  },
  {
    name = "vm-redeploy-public-ip-14"
  },
  {
    name = "vm-redeploy-public-ip-15"
  },
  {
    name = "vm-redeploy-public-ip-16"
  },
  {
    name = "vm-redeploy-public-ip-17"
  },
  {
    name = "vm-redeploy-public-ip-18"
  },
  {
    name = "vm-redeploy-public-ip-19"
  },
  {
    name = "vm-redeploy-public-ip-20"
  }
]

network_config_list = [
  {
    role               = "network"
    vnet_name          = "vm-redeploy-vnet"
    vnet_address_space = "10.1.0.0/16"
    subnet = [
      {
        name           = "vm-redeploy-subnet"
        address_prefix = "10.1.1.0/24"
      }
    ],
    network_security_group_name = "vm-redeploy-nsg"
    nic_public_ip_associations = [
      {
        nic_name              = "vm-redeploy-nic-1"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-1"
      },
      {
        nic_name              = "vm-redeploy-nic-2"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-2"
      },
      {
        nic_name              = "vm-redeploy-nic-3"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-3"
      },
      {
        nic_name              = "vm-redeploy-nic-4"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-4"
      },
      {
        nic_name              = "vm-redeploy-nic-5"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-5"
      },
      {
        nic_name              = "vm-redeploy-nic-6"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-6"
      },
      {
        nic_name              = "vm-redeploy-nic-7"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-7"
      },
      {
        nic_name              = "vm-redeploy-nic-8"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-8"
      },
      {
        nic_name              = "vm-redeploy-nic-9"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-9"
      },
      {
        nic_name              = "vm-redeploy-nic-10"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-10"
      },
      {
        nic_name              = "vm-redeploy-nic-11"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-11"
      },
      {
        nic_name              = "vm-redeploy-nic-12"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-12"
      },
      {
        nic_name              = "vm-redeploy-nic-13"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-13"
      },
      {
        nic_name              = "vm-redeploy-nic-14"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-14"
      },
      {
        nic_name              = "vm-redeploy-nic-15"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-15"
      },
      {
        nic_name              = "vm-redeploy-nic-16"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-16"
      },
      {
        nic_name              = "vm-redeploy-nic-17"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-17"
      },
      {
        nic_name              = "vm-redeploy-nic-18"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-18"
      },
      {
        nic_name              = "vm-redeploy-nic-19"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-19"
      },
      {
        nic_name              = "vm-redeploy-nic-20"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-ip-config"
        public_ip_name        = "vm-redeploy-public-ip-20"
      }
    ]
    nsr_rules = [{
      name                       = "nsr-ssh"
      priority                   = 100
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "2222"
      source_address_prefix      = "*"
      destination_address_prefix = "*"
      },
      {
        name                       = "nsr-rdp"
        priority                   = 101
        direction                  = "Inbound"
        access                     = "Allow"
        protocol                   = "Tcp"
        source_port_range          = "*"
        destination_port_range     = "3389"
        source_address_prefix      = "*"
        destination_address_prefix = "*"
      }
    ]
  }
]

vm_config_list = [{
  role           = "vm-redeploy-role"
  vm_name        = "vm-redeploy-1"
  nic_name       = "vm-redeploy-nic-1"
  admin_username = "ubuntu"
  zone           = "1"
  source_image_reference = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-2"
    nic_name       = "vm-redeploy-nic-2"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-3"
    nic_name       = "vm-redeploy-nic-3"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-4"
    nic_name       = "vm-redeploy-nic-4"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-5"
    nic_name       = "vm-redeploy-nic-5"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-6"
    nic_name       = "vm-redeploy-nic-6"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-7"
    nic_name       = "vm-redeploy-nic-7"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-8"
    nic_name       = "vm-redeploy-nic-8"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-9"
    nic_name       = "vm-redeploy-nic-9"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-10"
    nic_name       = "vm-redeploy-nic-10"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-11"
    nic_name       = "vm-redeploy-nic-11"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-12"
    nic_name       = "vm-redeploy-nic-12"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-13"
    nic_name       = "vm-redeploy-nic-13"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-14"
    nic_name       = "vm-redeploy-nic-14"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-15"
    nic_name       = "vm-redeploy-nic-15"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-16"
    nic_name       = "vm-redeploy-nic-16"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-17"
    nic_name       = "vm-redeploy-nic-17"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-18"
    nic_name       = "vm-redeploy-nic-18"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-19"
    nic_name       = "vm-redeploy-nic-19"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
  },
  {
    role           = "vm-redeploy-role"
    vm_name        = "vm-redeploy-20"
    nic_name       = "vm-redeploy-nic-20"
    admin_username = "ubuntu"
    zone           = "1"
    source_image_reference = {
      publisher = "Canonical"
      offer     = "0001-com-ubuntu-server-jammy"
      sku       = "22_04-lts"
      version   = "latest"
    }
    create_vm_extension = true
}]