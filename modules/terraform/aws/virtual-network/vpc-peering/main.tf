data "aws_vpc" "client_vpc"{
    vpc_name = "client-vpc"
}

data "aws_vpc" "server_vpc"{
    vpc_name = "server_vpc"
}

resource "aws_vpc_peering_connection" "serverclientpeer" {
    peer_vpc_id = data.aws_vpc.client_vpc.id
    vpc_id = data.aws_vpc.server_vpc.id
    peer_region = data.aws_vpc.server_vpc.region
    auto_accept = true
}