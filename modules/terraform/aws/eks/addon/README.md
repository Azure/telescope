# EKS Addon Module

This module provisions addons for an Amazon Elastic Kubernetes Service (EKS) cluster. It allows you to deploy various EKS addons with customizable configurations.

## Input Variables

### `cluster_name`

- **Description:** Value of the EKS cluster name.
- **Type:** String

### `cluster_oidc_provider_url`

- **Description:** Value of the EKS cluster OIDC provider URL.
- **Type:** String

### `tags`

- **Description:** A map of tags to add to all resources.
- **Type:** Map of strings
- **Default:** None

### `eks_addon_config_map`

- **Description:** A map of EKS addons to deploy.
- **Type:** Map of objects
  - `name`: Name of the addon
  - `version`: Version of the addon (optional)
  - `service_account`: Service account associated with the addon (optional)
  - `policy_arns`: Policy ARNs required for the addon (optional)

## Usage Example

```hcl
module "eks_addons" {
  source = "./eks-addon-module"

  cluster_name               = "my-cluster"
  cluster_oidc_provider_url  = "https://oidc.eks.region.amazonaws.com/id/EXAMPLED539D4633E4DE37FB1E5DAF51BDA"
  
  tags = {
    environment = "production"
    project     = "example"
  }

  eks_addon_config_map = {
    kubernetesDashboard = {
      name            = "kubernetes-dashboard"
      version         = "v2.0.0"
      service_account = "eks-dashboard-sa"
    }
    awsLoadBalancerController = {
      name            = "aws-load-balancer-controller"
      version         = "v2.3.0"
      service_account = "aws-load-balancer-controller-sa"
      policy_arns     = [
        "arn:aws:iam::aws:policy/ELBv2KubernetesServicePolicy",
        "arn:aws:iam::aws:policy/AWSLoadBalancerControllerIAMPolicy"
      ]
    }
  }
}
```

## Terraform Provider References

## Resources

- [aws_iam_openid_connect_provider Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_openid_connect_provider)
- [aws_iam_policy_document Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document)
- [aws_iam_role Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role)
- [aws_iam_role_policy_attachment Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment)
- [aws_eks_addon Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_addon)

## Data Sources
- [tls_certificate Documentation](https://registry.terraform.io/providers/hashicorp/tls/latest/docs/data-sources/certificate)
- [aws_iam_policy_document Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document)