scenario_type = "perf-eval"
scenario_name = "apiserver-vn100pod3k"
owner         = "aks"
network_config_list = [
  {
    role     = "client"
    vpc_name = "client-vpc"
    vpc_cidr = "10.0.0.0/16"
    subnets = [
      {
        name                = "client-subnet"
        cidr                = "10.0.0.0/24"
        secondary_ip_ranges = []
    }]
    firewall_rules = [
      {
        name               = "allow-all-egress"
        direction          = "EGRESS"
        priority           = 1000
        source_ranges      = []
        destination_ranges = ["0.0.0.0/0"]
        source_tags        = []
        target_tags        = []
        allow = [
          {
            protocol = "all"
            ports    = []
          }
        ]
      }
    ]
  }
]

gke_config_list = [
  {
    role        = "client"
    name        = "vn100p3k"
    vpc_name    = "client-vpc"
    subnet_name = "client-subnet"
    default_node_pool = {
      name         = "default",
      machine_type = "n1-standard-8",
      node_count   = 2
    }
    extra_node_pools = [
      {
        name         = "runner",
        machine_type = "n1-standard-16",
        node_count   = 1
      }
    ]
}]
