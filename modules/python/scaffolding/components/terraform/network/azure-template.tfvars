network_config_list = [
  {
    role               = "slo"
    vnet_name          = "slo-vnet"
    vnet_address_space = "10.0.0.0/9"
    subnet = [
      {
        name           = "slo-subnet-1"
        address_prefix = "10.0.0.0/16"
      }
    ]
    network_security_group_name = ""
    nic_public_ip_associations  = []
    nsr_rules                   = []
  }
]
