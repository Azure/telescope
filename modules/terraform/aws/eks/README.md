# Terraform EKS Module

This Terraform module allows you to provision an Amazon Elastic Kubernetes Service (EKS) cluster along with managed node groups and optional addons. The module simplifies the setup process and provides flexibility for different EKS configurations.

## Usage

To use the EKS module, follow these steps:

1. **Create EKS cluster & Managed Node Groups:**

   Include the configuration in your input tfvars file:

   ```
   eks_config_list = [{
   	eks_name                = "sumanth-test"
   	vpc_name                = "client-vpc"
   	policy_arns = ["AmazonEKSClusterPolicy", "AmazonEKSVPCResourceController", "AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"]
   	eks_managed_node_groups = [
   		{
   			name           = "node-group-1"
   			ami_type       = "AL2_x86_64"
   			instance_types = ["t3.small"]
   			min_size       = 1
   			max_size       = 3
   			desired_size   = 2
   			capacity_type = "ON_DEMAND" # Optional input
   			labels         = { terraform = "true", k8s = "true", role = "perf-eval" } # Optional input
   		}
   	]
   }]
   ```

   - This configuration creates EKS cluster using specified VPC.
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
     }
   ]
   ```
	 
   - For EKS addon's we have to create OIDC provider for the cluster and attach policy arns.[Refer here](https://docs.aws.amazon.com/eks/latest/userguide/managing-ebs-csi.html)
   - This configuration creates two addons related to storage.
   - service_account and policy_attachment_names are optional in general but some addons are required to have IAM permisson values. [Refer here](https://docs.aws.amazon.com/eks/latest/userguide/eks-add-ons.html)
   - We can also provide the version of an addon we are created which is an optional input here.
   -
