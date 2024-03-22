data "aws_vpc" "client_vpc"{
    tags = {
        Name = "client-vpc"
        Run_ID = var.run_id
    }
}

data "aws_vpc" "server_vpc"{
    tags = {
        Name = "server-vpc"
        Run_ID = var.run_id
    }
}

data "aws_instances" "client_instance" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.client_vpc.id]
  }
}

output "client_vpc_region" {
  value = data.aws_instances.client_instance.availability_zones[0]
}

resource "aws_vpc_peering_connection" "serverclientpeer" {
    peer_vpc_id = data.aws_vpc.client_vpc.id
    vpc_id = data.aws_vpc.server_vpc.id
    peer_region = client_vpc_region
    auto_accept = true
}