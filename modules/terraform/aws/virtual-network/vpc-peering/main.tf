data "aws_vpc" "client_vpc"{
    tags = {
        Name = "client-vpc"
        run_id = var.run_id
    }
}

data "aws_vpc" "server_vpc"{
    tags = {
        Name = "server-vpc"
        run_id = var.run_id
    }
}

resource "aws_vpc_peering_connection" "serverclientpeer" {
    peer_vpc_id = data.aws_vpc.client_vpc.id
    vpc_id = data.aws_vpc.server_vpc.id
    peer_region = var.peer_region
    auto_accept = true
}