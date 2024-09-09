resource "aws_ec2_transit_gateway" "transit_gateway" {
    description = "Transit Gateway" 
}

resource "aws_ec2_transit_gateway_vpc_attachment" "vpc_attachment" {
    depends_on = aws_ec2_transit_gateway.transit_gateway
    subnet_ids = var.subnet_ids
    transit_gateway_id = aws_ec2_transit_gateway.transit_gateway.id
    vpc_id = var.vpc_id
}

resource "aws_ec2_transit_gateway_connect" "connect" {
    depends_on = [aws_ec2_transit_gateway_vpc_attachment.vpc_attachment, aws_ec2_transit_gateway.transit_gateway]
    transport_attachment_id = aws_ec2_transit_gateway_vpc_attachment.vpc_attachment.vpc_id
    transit_gateway_id = aws_ec2_transit_gateway.transit_gateway.id
}