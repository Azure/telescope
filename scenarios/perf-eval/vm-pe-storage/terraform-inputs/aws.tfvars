scenario_type  = "perf-eval"
scenario_name  = "vm-pe-storage"
deletion_delay = "2h"

bucket_name_prefix = "vm-pe-storage" # should be same with $BUCKET_NAME_PREFIX in the script
bucket_file_key    = "test"
bucket_source_path = "client-userdata.sh"

vm_config_list = [{
  vm_name                     = "client-vm"
  role                        = "client"
  subnet_name                 = "same-subnet"
  security_group_name         = "same-sg"
  associate_public_ip_address = true
  zone_suffix                 = "b"
  }
]

network_config_list = [
  {
    role           = "network"
    vpc_name       = "same-vpc"
    vpc_cidr_block = "10.2.0.0/16"
    subnet = [{
      name        = "same-subnet"
      cidr_block  = "10.2.1.0/24"
      zone_suffix = "b"
    }]
    security_group_name = "same-sg"
    route_tables = [
      {
        name       = "internet-rt"
        cidr_block = "0.0.0.0/0"
      }
    ],
    route_table_associations = [
      {
        name             = "same-subnet-rt-assoc"
        subnet_name      = "same-subnet"
        route_table_name = "internet-rt"
      }
    ]
    sg_rules = {
      ingress = [
        {
          from_port  = 2222
          to_port    = 2222
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 80
          to_port    = 80
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        },
        {
          from_port  = 443
          to_port    = 443
          protocol   = "tcp"
          cidr_block = "0.0.0.0/0"
        }
      ]
      egress = [
        {
          from_port  = 0
          to_port    = 0
          protocol   = "-1"
          cidr_block = "0.0.0.0/0"
        }
      ]
    }
  },
]

pe_config = {
  pe_vpc_name  = "same-vpc"
  service_name = "com.amazonaws.us-east-2.s3"
}