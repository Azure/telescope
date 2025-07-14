override_data {
  target = module.eks["eks_name"].data.aws_iam_policy_document.assume_role
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
  target = module.eks["eks_name"].aws_iam_role.eks_cluster_role
  values = { arn = "arn:aws:iam::123456789012:role/eks_cluster_role" }
}

override_resource {
  target = module.eks["eks_name"].aws_eks_cluster.eks
  values = {
    identity = [{
      oidc = [{
        issuer = "https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
      }]
    }]
  }
}

override_resource {
  target = module.eks["eks_name"].aws_launch_template.launch_template["default"]
  values = {
    id = "lt-0abcd1234efgh5678"
  }
}

override_resource {
  target = module.eks["eks_name"].aws_launch_template.launch_template["userpool"]
  values = {
    id = "lt-0abcd1234efgh5679"
  }
}