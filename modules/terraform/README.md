# Terraform Modules

This folder contains Terraform modules for provisioning various resources on cloud providers. Below is the list of modules currently supported for AWS and Azure:

## AWS Modules

- **[S3 Bucket:](./aws/bucket/README.md)** Module for creating buckets on cloud storage services.
- **[EFS:](./aws/efs/README.md)** Module for provisioning Elastic File System (EFS) resources.
- **[EKS:](./aws/eks/README.md)** Module for setting up Amazon Elastic Kubernetes Service (EKS) clusters.
- **[Load Balancer:](./aws/load-balancer/README.md)** Module for creating load balancers.
- **[Private Link:](./aws/private-link/README.md)** Module for managing AWS PrivateLink connections.
- **[Virtual Machine:](./aws/virtual-machine/README.md)** Module for deploying virtual machines on AWS.
- **[Virtual Network:](./aws/virtual-network/README.md)** Module for configuring networking resources on AWS including a VPC, subnets, security groups, route tables, and associated resources.
- **[Placement Group:](./aws/placement-group/README.md)** Module for deploying a placement group on AWS .

## Azure Modules

- **[AKS:](./azure/aks/README.md)** Module for setting up Azure Kubernetes Service (AKS) clusters.
- **[Application Gateway:](./azure/app-gateway/README.md)** Module for configuring Azure Application Gateway.
- **[Data Disk:](./azure/data-disk/README.md)** Module for provisioning data disks on Azure VMs.
- **[Load Balancer:](./azure/load-balancer/README.md)** Module for creating load balancers on Azure.
- **[Network:](./azure/network/README.md)** Module for configuring networking resources on Azure.
- **[Data Connection:](./azure/onboarding/data-connection/Readme.md)** Module for creating data connections and kusto tables on Azure.
- **[Private Link:](./azure/private-link/README.md)** Module for managing Azure Private Link connections.
- **[Public IP:](./azure/public-ip/README.md)** Module for managing public IP addresses on Azure.
- **[Storage Account:](./azure/storage-account/README.md)** Module for creating storage accounts on Azure.
- **[Virtual Machine:](./azure/virtual-machine/README.md)** Module for deploying virtual machines on Azure.
- **[VMSS:](./azure/virtual-machine-scale-set/README.md)** Module for deploying virtual machine scale sets on Azure.
- **[Proximity Placement Group:](./azure/proximity-placement-group/README.md)** Module for deploying a proximity placement group on Azure .
- **[ExpressRoute:](./azure/express-route/README.md)** Module for deploying an express Route on Azure. 

## Usage
Each module contains its own README with specific instructions on usage and configuration.
