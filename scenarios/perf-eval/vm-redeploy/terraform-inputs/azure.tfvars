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
  }
]

network_config_list = [
  {
    role                        = "network"
    vnet_name                   = "vm-redeploy-vnet"
    vnet_address_space          = "10.1.0.0/16"
    subnet = [
        {
        name           = "vm-redeploy-subnet"
        address_prefix = "10.1.1.0/24"
      }
    ],
    network_security_group_name = ""
    nic_public_ip_associations  = [
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
      }
    ]
    nsr_rules                   = []
  }
]

vm_config_list = [{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-1"  
  nic_name       =  "vm-redeploy-nic-1"  
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
},
{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-2"  
  nic_name       =  "vm-redeploy-nic-2"   
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
},
{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-3"  
  nic_name       =  "vm-redeploy-nic-3"  
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
},
{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-4"  
  nic_name       =  "vm-redeploy-nic-4"  
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
},
{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-5"  
  nic_name       =  "vm-redeploy-nic-5"  
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
},
{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-6"  
  nic_name       =  "vm-redeploy-nic-6"  
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
},
{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-7"  
  nic_name       =  "vm-redeploy-nic-7"  
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
},
{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-8"  
  nic_name       =  "vm-redeploy-nic-8"  
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
},
{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-9"  
  nic_name       =  "vm-redeploy-nic-9"  
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
},
{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy-10"  
  nic_name       =  "vm-redeploy-nic-10"  
  admin_username =  "ubuntu"  
  zone           =  "1"  
  source_image_reference = {  
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
  create_vm_extension = false
}]