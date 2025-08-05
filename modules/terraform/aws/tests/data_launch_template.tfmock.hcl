override_data {
  target = module.eks["eks_launch_template_test"].data.aws_iam_policy_document.assume_role
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
  target = module.eks["eks_launch_template_test"].aws_iam_role.eks_cluster_role
  values = { arn = "arn:aws:iam::123456789012:role/eks_cluster_role" }
}

override_resource {
  target = module.eks["eks_launch_template_test"].aws_eks_cluster.eks
  values = {
    identity = [{
      oidc = [{
        issuer = "https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
      }]
    }]
  }
}

override_resource {
  target = module.eks["eks_launch_template_test"].aws_launch_template.launch_template["ng-with-network-interfaces"]
  values = {
    id             = "lt-0abcd1234efgh5678"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_launch_template_test"].aws_launch_template.launch_template["ng-ena-express-only"]
  values = {
    id             = "lt-0abcd1234efgh5679"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_launch_template_test"].aws_launch_template.launch_template["ng-with-capacity-reservation"]
  values = {
    id             = "lt-0abcd1234efgh567a"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_launch_template_test"].aws_launch_template.launch_template["ng-with-spot-instances"]
  values = {
    id             = "lt-0abcd1234efgh567b"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_launch_template_test"].aws_launch_template.launch_template["ng-baseline"]
  values = {
    id             = "lt-0abcd1234efgh567c"
    latest_version = 1
  }
}

override_resource {
  target = module.eks["eks_launch_template_test"].aws_launch_template.launch_template["ng-precedence-test"]
  values = {
    id             = "lt-0abcd1234efgh567d"
    latest_version = 1
  }
}

override_data {
  target = module.network["lt-test-vpc"].data.aws_subnets.subnets
  values = {
    ids = ["subnet-12345678901234567"]
  }
}

override_data {
  target = module.network["lt-test-vpc"].data.aws_subnet.subnet_details["lt-test-subnet"]
  values = {
    id = "subnet-12345678901234567"
  }
}

override_resource {
  target = module.eks["eks_launch_template_test"].aws_iam_openid_connect_provider.oidc_provider
  values = {
    arn = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-west-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
    url = "https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
  }
}

override_data {
  target = module.eks["eks_launch_template_test"].data.tls_certificate.eks
  values = {
    certificates = [{
      sha1_fingerprint = "9e99a48a9960b14926bb7f3b02e22da2b0ab7280"
    }]
  }
}
