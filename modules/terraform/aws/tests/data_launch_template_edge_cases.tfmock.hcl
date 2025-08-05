override_data {
  target = module.eks["eks_edge_test"].data.aws_iam_policy_document.assume_role
  values = {
    json = <<EOT
    {
      "Statement": [{
        "Effect": "Allow",
        "Principal": {
          "Service": ["eks.amazonaws.com", "ec2.amazonaws.com"]
        },
        "Action": ["sts:AssumeRole", "sts:TagSession"]
      }]
    } 
    EOT
  }
}

override_resource {
  target = module.eks["eks_edge_test"].aws_iam_role.eks_cluster_role
  values = { arn = "arn:aws:iam::123456789012:role/eks_cluster_role" }
}

override_resource {
  target = module.eks["eks_edge_test"].aws_eks_cluster.eks
  values = {
    identity = [{
      oidc = [{
        issuer = "https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
      }]
    }]
  }
}

override_resource {
  target = module.eks["eks_edge_test"].aws_launch_template.launch_template["ng-capacity-with-resource-group"]
  values = {
    id             = "lt-edge001"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_edge_test"].aws_launch_template.launch_template["ng-capacity-open"]
  values = {
    id             = "lt-edge002"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_edge_test"].aws_launch_template.launch_template["ng-spot-full-config"]
  values = {
    id             = "lt-edge003"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_edge_test"].aws_launch_template.launch_template["ng-ena-express-disabled"]
  values = {
    id             = "lt-edge004"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_edge_test"].aws_launch_template.launch_template["ng-partial-network-config"]
  values = {
    id             = "lt-edge005"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_edge_test"].aws_launch_template.launch_template["ng-global-ena-true-node-false"]
  values = {
    id             = "lt-edge006"
    latest_version = 1
  }
}

override_data {
  target = module.network["edge-test-vpc"].data.aws_subnets.subnets
  values = {
    ids = ["subnet-edge123456789012"]
  }
}

override_data {
  target = module.network["edge-test-vpc"].data.aws_subnet.subnet_details["edge-test-subnet"]
  values = {
    id = "subnet-edge123456789012"
  }
}

override_resource {
  target = module.eks["eks_edge_test"].aws_iam_openid_connect_provider.oidc_provider
  values = {
    arn = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-west-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
    url = "https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
  }
}

override_data {
  target = module.eks["eks_edge_test"].data.tls_certificate.eks
  values = {
    certificates = [{
      sha1_fingerprint = "9e99a48a9960b14926bb7f3b02e22da2b0ab7280"
    }]
  }
}
