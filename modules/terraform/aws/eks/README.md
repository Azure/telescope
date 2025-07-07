# Terraform EKS Module

This Terraform module allows you to provision an Amazon Elastic Kubernetes Service (EKS) cluster along with managed node groups and optional addons. The module simplifies the setup process and provides flexibility for different EKS configurations.

## Usage

To use the EKS module, follow these steps:

1. **Create EKS cluster & Managed Node Groups:**

  Include the configuration in your input tfvars file:

```hcl
  eks_config_list = [{
  eks_name                = "eks-test"
  vpc_name                = "client-vpc"
  policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
  eks_managed_node_groups = [
    {
      name           = "node-group-1"
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["t3.small"]
      min_size       = 1
      max_size       = 3
      desired_size   = 2
      capacity_type = "ON_DEMAND" # Optional input
      ena_express    = true # Optional (default: null)
      labels         = { terraform = "true", k8s = "true", role = "perf-eval" } # Optional input
      taints         = [{
        key = "dedicated"
        value = "fio"
        effect = "NO_SCHEDULE"
      }] # Optional input
    }
  ]
  }]
```

- This configuration creates EKS cluster using specified VPC.
  - You need to have at least 2 subnets in different zones with public ip enabled for each subnet to be able to successfully create the cluster.
  - We need few IAM permission in order to create Node Group. Please refer [here](https://docs.aws.amazon.com/eks/latest/userguide/create-node-role.html)
  - Recommended to have these polices added to your tfvars. ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEC2ContainerRegistryReadOnly", "AmazonEKS_CNI_Policy"]
- It also creates an IAM role and attachs the polices listed in the tfvars config.
- It creates one node group for the cluster with our desired configuration.
- policy_arns is the list of suffix strings of policy we want to attach to a IAM role.
- For Example: Policy ARN : arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy
  In the given example policy arn is "service-role/AmazonEBSCSIDriverPolicy"

2. **Create EKS Addon:**

   To create EKS addon include this configuration to the eks_config_list object.

   ```
   eks_addons = [{
     name                    = "aws-ebs-csi-driver"
     service_account         = "ebs-csi-controller-sa"
     policy_arns = ["service-role/AmazonEBSCSIDriverPolicy"]
     },
     {
       name                    = "aws-efs-csi-driver"
       service_account         = "efs-csi-*"
       policy_arns = ["service-role/AmazonEFSCSIDriverPolicy"]
     },
     {
       name = "coredns"
     }
   ]
   ```

- **Description:** A list of maps of EKS addons to deploy.
- **Type:** Map of objects
  - `name`: Name of the addon
  - `version`: Version of the addon (optional)
  - `service_account`: Service account associated with the addon (optional)
  - `policy_arns`: Policy ARNs required for the addon (optional)
  - `before_compute`: Create addon before creating the managed node groups (default = false)
- For EKS addon's we have to create OIDC provider for the cluster and attach policy arns.[Refer here](https://docs.aws.amazon.com/eks/latest/userguide/managing-ebs-csi.html)
- This configuration creates two addons related to storage.
- service_account and policy_attachment_names are optional in general but some addons are required to have IAM permisson values. [Refer here](https://docs.aws.amazon.com/eks/latest/userguide/eks-add-ons.html)
- We can also provide the version of an addon we are created which is an optional input here.
- For VPC-CNI, a default configuration is used (see [main.tf](./main.tf)). Use vpc_cni_warm_prefix_target to set WARM_PREFIX_TARGET (default: 1)

3. **Config override**

The optional field `k8s_machine_type` overrides, when set, the `instance_types` value of all EKS nodes defined in `eks_managed_node_groups`. This is useful to define scenarios with different instance types using the same base config. Valid values can be found in the [AWS EC2 instance types documentation](https://aws.amazon.com/ec2/instance-types/).

The optional field `ena_express` overrides the `ena_express` value of all EKS nodes defined in `eks_managed_node_groups`. See more about ENA (Enhanced Networking Experience) express in [AWS ENA Express documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ena-express.html).

## Terraform Provider References

### Resources

- [aws_iam_role Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role)
- [aws_iam_role_policy_attachment Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment)
- [aws_iam_openid_connect_provider Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_openid_connect_provider)
- [aws_eks_cluster Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_cluster)
- [aws_eks_node_group Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_node_group)
- [aws_eks_addon Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_addon)
- [module Documentation](https://www.terraform.io/docs/language/modules/index.html)

### Data Sources

- [aws_iam_policy_document Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document)
- [aws_subnets Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnets)
- [tls_certificate Documentation](https://registry.terraform.io/providers/hashicorp/tls/latest/docs/data-sources/certificate)
