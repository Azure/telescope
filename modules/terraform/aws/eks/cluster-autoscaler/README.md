# EKS Cluster Autoscaler Module

## Overview

This module configures the Cluster Autoscaler for an Amazon EKS (Elastic Kubernetes Service) cluster. The Cluster Autoscaler automatically adjusts the size of a Kubernetes cluster based on the resource requests and limits set in your applications, ensuring optimal resource utilization and cost efficiency.

## Module Structure

The module consists of several key components:

1. **IAM Role and Policy**: Creates an IAM role with policies that allow the Cluster Autoscaler to manage EC2 instances and Auto Scaling groups.
2. **Kubernetes Resources**: Deploys the Cluster Autoscaler as a Kubernetes deployment within the `kube-system` namespace, along with the necessary RBAC (Role-Based Access Control) permissions.
3. **Configuration Variables**: Provides customizable variables for deployment configuration.

## Variables

- `region` (string): The AWS region where the EKS cluster is located.
- `cluster_name` (string): The name of the EKS cluster.
- `tags` (map(string)): Tags to apply to AWS resources.
- `cluster_iam_role_name` (string): The IAM role associated with the EKS cluster.
- `cluster_version` (string): The version of the cluster, used to tag the autoscaler image.

## Usage

To use this module in your Terraform configuration, include the following block:

```hcl
module "cluster_autoscaler" {
  source                  = "./cluster-autoscaler"
   region                  = "us-west-2"
  cluster_name            = "my-eks-cluster"
  tags                    = {
    Environment = "production"
  }
  cluster_iam_role_name   = "my-cluster-iam-role"
  cluster_version         = "1.30"
}
```

Notes:
- Cluster Autoscaler is deployed on the node groups with the label autoscaler=owned.
- Add taints and labels for node groups to be managed by the Cluster Autoscaler.
