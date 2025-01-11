network_config_list = [
  {
    role               = "client"
    vnet_name          = "client-vnet"
    vnet_address_space = "10.0.0.0/16"
    subnet = [
      {
        name           = "client-subnet"
        address_prefix = "10.0.0.0/24"
      }
    ]
    network_security_group_name = "client-sg"
        nic_public_ip_associations = [
      {
        nic_name              = "client-nic"
        subnet_name           = "client-subnet"
        ip_configuration_name = "client-ipconfig"
        public_ip_name        = "client-pip"
      }
    
    nsr_rules                   = []
  }
]
