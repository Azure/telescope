scenario_type  = "perf-eval"  
scenario_name  = "vm-redeploy"  
deletion_delay = "2h"  

public_ip_config_list = [{
  name = "vm-redeploy-pip"
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
    network_security_group_name = "vm-redeploy-nsg"
    nic_public_ip_associations  = [
      {
        nic_name              = "vm-redeploy-nic"
        subnet_name           = "vm-redeploy-subnet"
        ip_configuration_name = "vm-redeploy-config"
        public_ip_name        = "vm-redeploy-pip"
      }
    ]
    nsr_rules = [{  # List of Network Security Rules
      name                       =  "nsr-ping"  # Name of the Network Security Rule (e.g., "nsr-ssh")
      priority                   =  100  # Priority of the rule (e.g., 100)
      direction                  =  "Inbound"  # Direction of traffic (e.g., "Inbound")
      access                     =  "Allow"  # Access permission (e.g., "Allow")
      protocol                   =  "Icmp"  # Protocol for the rule (e.g., "Tcp")
      source_port_range          =  "*"  # Source port range (e.g., "*")
      destination_port_range     =  "*"  # Destination port range (e.g., "2222")
      source_address_prefix      =  "*"  # Source address prefix (e.g., "*")
      destination_address_prefix =  "*"  # Destination address prefix (e.g., "*")
      }
    ]
  }
]

vm_config_list = [{  
  role           =  "vm-redeploy-role"  
  vm_name        =  "vm-redeploy"  
  nic_name       =  "vm-redeploy-nic"  
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