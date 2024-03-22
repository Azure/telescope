# Terraform Modules

This repository contains Terraform modules for provisioning various resources on cloud providers. Below is the list of modules currently supported for AWS and Azure:

## AWS Modules

- **[S3 Bucket:](./aws/bucket/README.md)** Module for creating buckets on cloud storage services.
- **[EFS:](./aws/efs/README.md)** Module for provisioning Elastic File System (EFS) resources.
- **[EKS:](./aws/eks/README.md)** Module for setting up Amazon Elastic Kubernetes Service (EKS) clusters.
- **[Load Balancer:](./aws/load-balancer/README.md)** Module for creating load balancers.
- **[Private Link:](./aws/private-link/README.md)** Module for managing AWS PrivateLink connections.
- **[Virtual Machine:](./aws/virtual-machine/README.md)** Module for deploying virtual machines on AWS.
- **[Virtual Network:](./aws/virtual-network/README.md)** Module for configuring networking resources on AWS including a VPC, subnets, security groups, route tables, and associated resources.


## Azure Modules

- **[AKS:](./azure/aks/README.md)** Module for setting up Azure Kubernetes Service (AKS) clusters.
- **[Data Disk:](./azure/data-disk/README.md)** Module for provisioning data disks on Azure VMs.
- **[Network:](./azure/network/README.md)** Module for configuring networking resources on Azure.
- **[Private Link:](./azure/private-link/README.md)** Module for managing Azure Private Link connections.
- **[Storage Account:](./azure/storage-account/README.md)** Module for creating storage accounts on Azure.
- **[VMSS:](./azure/virtual-machine-scale-set/README.md)** Module for deploying virtual machine scale sets on Azure.
- **[Application Gateway:](./azure/app-gateway/README.md)** Module for configuring Azure Application Gateway.
- **[Load Balancer:](./azure/load-balancer/README.md)** Module for creating load balancers on Azure.
- **[Data Connection:](./azure/onboarding/data-connection/Readme.md)** Module for creating data connections and kusto tables on Azure.
- **[Public IP:](./azure/public-ip/README.md)** Module for managing public IP addresses on Azure.

## Usage

Each module contains its own README with specific instructions on usage and configuration.
