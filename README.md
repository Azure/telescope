# Telescope

This repository is part of the [Cloud Competitve Test Framework](https://microsoft-my.sharepoint.com/:w:/p/ansonqian/EWu1qhLEL-RBqimgsFBgb9EBWJlLPRc_w1FNaSYuY-UA7A?e=jikM3r). It stores test scenarios specific code, include terraform code for creating and managing infrastructure as code and python/bash code for test modules (e.g. iperf, jmeter, fio) integration. It works closely with the other part of the framework [ADO/telescope](https://msazure.visualstudio.com/CloudNativeCompute/_git/telescope) which stores test automation and reporting related code, including azure devops pipeline (yaml) code for test scheduling and execution, and azure data explorer dashboard (json) code for kusto query and data vizualization.

## Permissions

* Cloud resources (for manual local testing only)
  * Azure subscription: [Cloud Competitive Test](https://ms.portal.azure.com/#@microsoft.onmicrosoft.com/resource/subscriptions/c0d4b923-b5ea-4f8f-9b56-5390a9bf2248/overview) - ask owner to give you **Contributor** role
  * AWS account: ask owner to give you an account
* [Azure/telescope](https://github.com/Azure/telescope): make sure you join **Azure** organization using this [link](https://repos.opensource.microsoft.com/orgs) and your personal GitHub account. Once done, ask owner to give you access to the repository.

*Note*: Owners can be found in [owners.txt](owners.txt)

## Repository Hierarchy
```
.github
└── workflows
modules
├── bash
├── python
└── terraform
    ├── aws
    └── azure
scenarios
└── issue-repo <Scenario-Type>
    └── lb-tls-error <Scenario-Name>
        ├── bash-scripts
        ├── https
        ├── terraform-inputs*
        ├── terraform-test-inputs*
        └── Makefile
    └── perf-eval <Scenario-Type>
        └── vm-iperf <Scenario-Name>
            ├── bash-scripts
            ├── terraform-inputs*
            └── terraform-test-inputs*
.gitignore
```

Note:
- Here * represents these folders are required for to create any tests using this framework.

### .github

This directory contains GitHub workflows, which automate various tasks like unit testing and validating the code.

- **workflows**: This folder Contains YAML files defining GitHub Actions.

### modules

This directory holds reusable scripts and configurations for automation tasks.

- **bash**: Contains Bash scripts for various automation tasks related to specifc to test scenario's and cloud.
- **python**: Contains Python scripts/modules for running various test scenario's.
- **terraform**: Contains Terraform configurations for managing cloud infrastructure related to AWS and Azure.

  - **aws**: Terraform module configurations specific to Amazon Web Services (AWS).
  - **azure**: Terraform module configurations specific to Microsoft Azure.

Note:
  - Please refer to this [Terraform Readme](./modules/terraform/README.md) to know about the modules we currently support for telescope framework.

### scenarios

This directory organizes different test scenarios inputs to evaluation the performance of different cloud components and reproduce issues we see in production.

- **issue-repo**: Contains test scenarios related to know issues that can to be replicated using telescope framework.
  Example:
  - **lb-tls-error**: Name of the issue we are trying to reproduce.

    - **bash-scripts**: Bash scripts for diagnosing or replicating TLS errors.
    - **https**: Files related to HTTPS configuration.
    - **terraform-inputs**: Input configurations for Terraform to create cloud resources.
    - **terraform-test-inputs**: Test input configurations for Terraform to run on github workflows.

  - **perf-eval**: Resources related to performance evaluation scenarios.

    - **vm-iperf**: Resources for evaluating VM network performance using iPerf.
      - **bash-scripts**: Bash scripts for diagnosing or replicating TLS errors.
      - **terraform-inputs**: Input configurations for Terraform to create cloud resources.
      - **terraform-test-inputs**: Test input configurations for Terraform to run on github workflows.

### .gitignore

Specifies files to ignore in version control.

## Create and run Test Scenarios

### Test Scenarios

* All existing test scenarios are located in the [Azure\telescope](https://github.com/Azure/telescope/tree/main/scenarios) folder.
* 

### Build a new test scenario

#### Main workflows

* Step 1: create a test branch with new test scenario(vm-diff-zone-iperf) in [Azure/telescope](https://github.com/Azure/telescope/tree/main/scenarios) repository.
* Step 2: create new folder under `scenarios\perf-eval\`  with `vm-diff-zone-iperf` and create subfolders terraform-inputs and terraform-test-inputs which are required for any test scenario.
* Step 3: Create aws.tfvars and azure.tfvars file inside terraform-inputs folder.
* Step 4: Create azure.json and aws.json files instead terraform-test-inputs folder.

Please find the templates for these files below:

**Azure tfvars Template:**

```hcl
scenario_type  = "perf-eval"  # Name of the scenario type (E.g perf-eval)
scenario_name  = "vm-diff-zone-iperf"  # Name of the scenario folder we created in the scenario/perf-eval (E.g vm-diff-zone-iperf)
deletion_delay = "2h"  # No of hours after which the resources can be deleted.

public_ip_config_list = [  # List of public IP address configurations to be created
  {
    name               = "ingress-pip"  # Name of the Public IP (e.g., "ingress-pip")
    allocation_method = "Static"  # Optional: Allocation method for the public IP (e.g., "Static")
    sku               = "Standard"  # Optional: SKU of the public IP (e.g., "Standard")
    zones             = [1, 2]  # Optional: Zones for the public IP (e.g., [1,2])
  }
]
network_config_list = [
  {
    role               = "client"  # Name of the role that will be used to identify the resources (E.g "client")
    vnet_name          = "client-vnet"  # Name of the VNET (E.g "client-vnet")
    vnet_address_space = "10.2.0.0/16"  # CIDR address for Vnet (E.g "10.2.0.0/16")
    subnet = [{
      name                         = "server-subnet"  # Name of the Subnet (e.g., "server-subnet")
      address_prefix               = "10.2.1.0/24"  # CIDR address for Subnet (e.g., "10.2.1.0/24")
      service_endpoints            = ["Microsoft.Storage"]  # Optional: List of service endpoints for the subnet (e.g., ["Microsoft.Storage"])
      pls_network_policies_enabled = true  # Optional: Flag indicating whether PLS network policies are enabled for the subnet
    }]
    network_security_group_name = "same-nsg"  # Name of the Network Security Group(E.g "same-nsg")
    nic_public_ip_associations = [ # List of NIC public IP associations
      {
        nic_name              =  "server-nic"  # Name of the Network Interface Card (NIC) (e.g., "server-nic")
        subnet_name           =  "same-subnet"  # Name of the subnet associated with the NIC (e.g., "same-subnet")
        ip_configuration_name =  "server-ipconfig"  # Name of the IP configuration for the NIC (e.g., "server-ipconfig")
        public_ip_name        =  "ingress-pip"  # Name of the public IP associated with the NIC (e.g., "ingress-pip")
      }
    ]
    nsr_rules = [{  # List of Network Security Rules
      name                       =  "nsr-ssh"  # Name of the Network Security Rule (e.g., "nsr-ssh")
      priority                   =  100  # Priority of the rule (e.g., 100)
      direction                  =  "Inbound"  # Direction of traffic (e.g., "Inbound")
      access                     =  "Allow"  # Access permission (e.g., "Allow")
      protocol                   =  "Tcp"  # Protocol for the rule (e.g., "Tcp")
      source_port_range          =  "*"  # Source port range (e.g., "*")
      destination_port_range     =  "2222"  # Destination port range (e.g., "2222")
      source_address_prefix      =  "*"  # Source address prefix (e.g., "*")
      destination_address_prefix =  "*"  # Destination address prefix (e.g., "*")
      }
    ]
  }
]
loadbalancer_config_list = [{
  role                  = "ingress"  # Role of the load balancer (e.g., "ingress")
  loadbalance_name      = "ingress-lb"  # Name of the load balancer (e.g., "ingress-lb")
  loadbalance_pool_name = "ingress-lb-pool"  # Name of the load balancer pool (e.g., "ingress-lb-pool")
  probe_protocol        = "Tcp"  # Protocol used for health probes (e.g., "Tcp")
  probe_port            = 20000  # Port used for health probes (e.g., 20000)
  probe_request_path    =  ""  # Request path used for health probes, if applicable
  is_internal_lb        = false  # Flag indicating whether the load balancer is internal or external
  subnet_name           =  "client-subnet"  # Name of the subnet where the load balancer is located (e.g., "client-subnet")
  lb_rules = [{  # List of load balancer rules
    type                     = "Inbound"  # Type of the rule (e.g., "Inbound")
    rule_count               = 1  # Number of rules (e.g., 1)
    role                     = "ingress-lb-tcp-rule"  # Role of the rule (e.g., "ingress-lb-tcp-rule")
    protocol                 = "Tcp"  # Protocol used for the rule (e.g., "Tcp")
    frontend_port            = 20001  # Frontend port for the rule (e.g., 20001)
    backend_port             = 20001  # Backend port for the rule (e.g., 20001)
    fronend_ip_config_prefix = "ingress"  # Prefix for the frontend IP configuration (e.g., "ingress")
    enable_tcp_reset         = false  # Flag indicating whether to enable TCP reset (e.g., false)
    idle_timeout_in_minutes  = 4  # Idle timeout in minutes (e.g., 4)
    }]
}]

vm_config_list = [{  # List of virtual machine configurations
  role           =  "server"  # Role of the virtual machine (e.g., "server")
  vm_name        =  "server-vm"  # Name of the virtual machine (e.g., "server-vm")
  nic_name       =  "server-nic"  # Name of the associated Network Interface Card (NIC) (e.g., "server-nic")
  admin_username =  "ubuntu"  # Username for accessing the virtual machine (e.g., "ubuntu")
  zone           =  "1"  # Availability zone for the virtual machine (e.g., "1")
  source_image_reference = {  # Reference to the source image for the virtual machine
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-focal"
    sku       = "20_04-lts"
    version   = "latest"
  }
  create_vm_extension = true  # Flag indicating whether to create a VM extension or not
}]

vmss_config_list = [{
  role                   =  "server"  # Role of the virtual machine scale set (e.g., "server")
  vmss_name              =  "server-vmss"  # Name of the virtual machine scale set (e.g., "server-vmss")
  nic_name               =  "server-nic"  # Name of the associated Network Interface Card (NIC) (e.g., "server-nic")
  subnet_name            =  "server-subnet"  # Name of the subnet for the virtual machine scale set (e.g., "server-subnet")
  loadbalancer_pool_name =  "ingress-lb-pool"  # Name of the load balancer pool associated with the virtual machine scale set (e.g., "ingress-lb-pool")
  ip_configuration_name  =  "server-ipconfig"  # Name of the IP configuration for the virtual machine scale set (e.g., "server-ipconfig")
  number_of_instances    =  2  # Number of instances in the virtual machine scale set (e.g., 2)
  admin_username         =  "adminuser"  # Username for accessing the virtual machines in the scale set (e.g., "adminuser")
  source_image_reference = {  # Reference to the source image for the virtual machine scale set
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
}]

nic_backend_pool_association_list = [
  {
    nic_name              = "server-nic"  # Name of the Network Interface Card (NIC) (e.g., "server-nic")
    backend_pool_name     = "ingress-lb-pool"  # Name of the backend pool associated with the NIC (e.g., "ingress-lb-pool")
    vm_name               = "server-vm"  # Name of the virtual machine associated with the NIC (e.g., "server-vm")
    ip_configuration_name = "server-ipconfig"  # Name of the IP configuration for the NIC (e.g., "server-ipconfig")
  }
]
```
**Aws tfvars Template:**
```hcl
scenario_type  = "perf-eval"  # Type of scenario (e.g., "perf-eval")
scenario_name  = "vm-diff-zone-iperf"  # Name of the scenario (e.g., "vm-diff-zone-iperf")
deletion_delay = "2h"  # Delay before resources can be deleted (e.g., "2h")
network_config_list = [  # List of network configurations
  {
    role           = "network"  # Role of the network configuration (e.g., "network")
    vpc_name       = "same-vpc"  # Name of the VPC (e.g., "same-vpc")
    vpc_cidr_block = "10.2.0.0/16"  # CIDR block for the VPC (e.g., "10.2.0.0/16")
    subnet = [  # List of subnets
      {
        name        = "client-subnet"  # Name of the subnet (e.g., "client-subnet")
        cidr_block  = "10.2.1.0/24"  # CIDR block for the subnet (e.g., "10.2.1.0/24")
        zone_suffix = "a"  # Availability zone suffix for the subnet (e.g., "a")
      },
      {
        name        = "server-subnet"  # Name of the subnet (e.g., "server-subnet")
        cidr_block  = "10.2.2.0/24"  # CIDR block for the subnet (e.g., "10.2.2.0/24")
        zone_suffix = "b"  # Availability zone suffix for the subnet (e.g., "b")
      }
    ]
    security_group_name = "same-sg"  # Name of the security group (e.g., "same-sg")
    route_tables = [  # List of route tables
      {
        name       = "internet-rt"  # Name of the route table (e.g., "internet-rt")
        cidr_block = "0.0.0.0/0"  # CIDR block for the route (e.g., "0.0.0.0/0")
      }
    ],
    route_table_associations = [  # List of route table associations
      {
        name             = "client-subnet-rt-assoc"  # Name of the association (e.g., "client-subnet-rt-assoc")
        subnet_name      = "client-subnet"  # Name of the subnet (e.g., "client-subnet")
        route_table_name = "internet-rt"  # Name of the route table (e.g., "internet-rt")
      },
      {
        name             = "server-subnet-rt-assoc"  # Name of the association (e.g., "server-subnet-rt-assoc")
        subnet_name      = "server-subnet"  # Name of the subnet (e.g., "server-subnet")
        route_table_name = "internet-rt"  # Name of the route table (e.g., "internet-rt")
      }
    ]
    sg_rules = {  # Security group rules
      ingress = [  # Ingress rules
        {
          from_port  = 2222  # Starting port for traffic (e.g., 2222)
          to_port    = 2222  # Ending port for traffic (e.g., 2222)
          protocol   = "tcp"  # Protocol for the rule (e.g., "tcp")
          cidr_block = "0.0.0.0/0"  # CIDR block for the rule (e.g., "0.0.0.0/0")
        },  
        {
          from_port  = 20002  # Starting port for traffic (e.g., 20002)
          to_port    = 20002  # Ending port for traffic (e.g., 20002)
          protocol   = "udp"  # Protocol for the rule (e.g., "udp")
          cidr_block = "0.0.0.0/0"  # CIDR block for the rule (e.g., "0.0.0.0/0")
        }
      ]
      egress = [  # Egress rules
        {
          from_port  = 0  # Starting port for traffic (e.g., 0)
          to_port    = 0  # Ending port for traffic (e.g., 0)
          protocol   = "-1"  # Protocol for the rule (e.g., "-1")
          cidr_block = "0.0.0.0/0"  # CIDR block for the rule (e.g., "0.0.0.0/0")
        }
      ]
    }
  },
]
loadbalancer_config_list = [{  # List of load balancer configurations
  role               = "ingress"  # Role of the load balancer (e.g., "ingress")
  vpc_name           = "same-vpc"  # Name of the VPC (e.g., "same-vpc")
  subnet_name        = "server-subnet"  # Name of the subnet (e.g., "server-subnet")
  load_balancer_type = "network"  # Type of load balancer (e.g., "network")
  lb_target_group = [{  # List of load balancer target groups
    role       = "nlb-tg"  # Role of the target group (e.g., "nlb-tg")
    tg_suffix  = "http"  # Suffix for the target group (e.g., "http")
    port       = 80  # Port for the target group (e.g., 80)
    protocol   = "TCP"  # Protocol for the target group (e.g., "TCP")
    rule_count = 1  # Number of rules for the target group (e.g., 1)
    vpc_name   = "server-vpc"  # Name of the VPC (e.g., "server-vpc")
    health_check = {  # Health check configuration
      port                = "80"  # Port for health checks (e.g., "80")
      protocol            = "TCP"  # Protocol for health checks (e.g., "TCP")
      interval            = 15  # Interval for health checks (e.g., 15)
      timeout             = 10  # Timeout for health checks (e.g., 10)
      healthy_threshold   = 3  # Healthy threshold for health checks (e.g., 3)
      unhealthy_threshold = 3  # Unhealthy threshold for health checks (e.g., 3)
    }
    lb_listener = {  # Load balancer listener configuration
      port     = 80  # Port for the listener (e.g., 80)
      protocol = "TCP"  # Protocol for the listener (e.g., "TCP")
    }
    lb_target_group_attachment = {  # Load balancer target group attachment configuration
      vm_name = "server-vm"  # Name of the virtual machine (e.g., "server-vm")
      port    = 80  # Port for the target group attachment (e.g., 80)
    }
    },
    {
      role       = "nlb-tg"  # Role of the target group (e.g., "nlb-tg")
      tg_suffix  = "https"  # Suffix for the target group (e.g., "https")
      port       = 443  # Port for the target group (e.g., 443)
      protocol   = "TCP"  # Protocol for the target group (e.g., "TCP")
      rule_count = 1  # Number of rules for the target group (e.g., 1)
      vpc_name   = "same-vpc"  # Name of the VPC (e.g., "same-vpc")
      health_check = {  # Health check configuration
        port                = "443"  # Port for health checks (e.g., "443")
        protocol            = "TCP"  # Protocol for health checks (e.g., "TCP")
        interval            = 15  # Interval for health checks (e.g., 15)
        timeout             = 10  # Timeout for health checks (e.g., 10)
        healthy_threshold   = 3  # Healthy threshold for health checks (e.g., 3)
        unhealthy_threshold = 3  # Unhealthy threshold for health checks (e.g., 3)
      }
      lb_listener = {  # Load balancer listener configuration
        port     = 443  # Port for the listener (e.g., 443)
        protocol = "TCP"  # Protocol for the listener (e.g., "TCP")
      }
      lb_target_group_attachment = {  # Load balancer target group attachment configuration
        vm_name = "server-vm"  # Name of the virtual machine (e.g., "server-vm")
        port    = 443  # Port for the target group attachment (e.g., 443)
      }
    }
  ]
}]

vm_config_list = [{  # List of virtual machine configurations
  vm_name                     = "client-vm"  # Name of the virtual machine (e.g., "client-vm")
  role                        = "client"  # Role of the virtual machine (e.g., "client")
  subnet_name                 = "client-subnet"  # Name of the subnet (e.g., "client-subnet")
  security_group_name         = "same-sg"  # Name of the security group (e.g., "same-sg")
  associate_public_ip_address = true  # Flag indicating whether to associate a public IP address (e.g., true)
  zone_suffix                 = "a"  # Availability zone suffix for the VM (e.g., "a")
},
{
  vm_name                     = "server-vm"  # Name of the virtual machine (e.g., "server-vm")
  role                        = "server"  # Role of the virtual machine (e.g., "server")
  subnet_name                 = "server-subnet"  # Name of the subnet (e.g., "server-subnet")
  security_group_name         = "same-sg"  # Name of the security group (e.g., "same-sg")
  associate_public_ip_address = true  # Flag indicating whether to associate a public IP address (e.g., true)
  zone_suffix                 = "b"  # Availability zone suffix for the VM (e.g., "b")
}
]

```
**Azure json Template:**
```json
{
    "owner"                            : "terraform_unit_tests",  // Owner of the resource (e.g., "terraform_unit_tests")
    "run_id"                           : "123456789",  // Run ID associated with the resource (e.g., "123456789")
    "region"                           : "eastus",  // Region where the resource is located (e.g., "eastus")
    "machine_type"                     : "Standard_D16_v5",  // Type of machine (e.g., "Standard_D16_v5")
    "accelerated_networking"           : true  // Whether accelerated networking is enabled or not (e.g., true)
}
```
**Aws json Template:**
```json
{
    "owner"         : "terraform_unit_tests",  // Owner of the resource (e.g., "terraform_unit_tests")
    "run_id"        : "123456789",  // Run ID associated with the resource (e.g., "123456789")
    "region"        : "us-east-1",  // AWS region where the resource is located (e.g., "us-east-1")
    "machine_type"  : "m5.4xlarge"  // Type of machine used  (e.g., "m5.4xlarge")
}

```

Note:
  - In this json files we add key values that are passed as arguments while running terraform apply.

* Step 5: Follow the instructions from this [readme](./scenarios/perf-eval/vm-iperf/README.md) and manually run the terraform code on your local machine before we test this on ADO pipeline.
* Step 6: After testing it successfull on your local machine. Push the changes to remote branch.
* Step 7: Create a new branch in the [ADO/telescope](https://msazure.visualstudio.com/CloudNativeCompute/_git/telescope) and update `SCENARIO_VERSION` to the branch/tag/SHA of where you change is in this [New Pipeline Test](https://dev.azure.com/msazure/CloudNativeCompute/_build?definitionId=338871)
* Step 8: trigger the pipeline [New Pipeline Test](https://dev.azure.com/msazure/CloudNativeCompute/_build?definitionId=338871) to run your test. To trigger, click the `Run pipeline` button in top right corner, then choose your branch under drop down menu under `Branch/tag` and click `Run` button in the bottom right corner.
* Step 9: once you verify the new test is working properly, create a new pipeline `yml` file under `pipelines` folder and in the corresponding subfolder depending on your test type (`perf-eval` or `issue-repro`). Move the content of the `new-pipeline-test.yml` to this new file and undo all changes made to the `new-pipeline-test.yml` file.
* Step 10: Create a new pull request to merge the github file changes to the main branch and ask owner to review the PR.
* Step 11: Once the GitHub PR is merged. Create a GitHub tag based on the changes you added in this PR. Please refer to the Tag documentation to create the tag.
* Step 12: Update the tag you created in the previous step and create the PR for ADO pipeline. Please refer to instructions [here](https://msazure.visualstudio.com/CloudNativeCompute/_git/telescope?path=/README.md)

### Update an existing test scenario

* Step 1: create a test branch in [Azure/telescope](https://github.com/Azure/telescope/tree/main/scenarios) repository.
* Step 2: navigate to the test scenario file you want to update and make the necessary changes. You can coordinate using `SCENARIO_TYPE` and `SCENARIO_NAME` to find the corresponding test scenario folder.

For example, if you want to update the `lb-same-zone-iperf` test scenario, then you should navigate to the [lb-same-zone-iperf](https://github.com/Azure/telescope/tree/main/scenarios/perf-eval/lb-same-zone-iperf) folder and make necessary changes.

* Step 3: update `SCENARIO_VERSION` to the branch/tag/SHA of where you change is in the [vm-lb-vm-same-zone-iperf2.yml](pipelines/perf-eval/vm-lb-vm-same-zone-iperf2.yml) file.

For example, if your branch name is `my-name/update-lb-iperf2` in `Azure/telescope`, then you should update `SCENARIO_VERSION` to `my-name/update-lb-iperf2`.

* Step 4: navigate to the corresponding pipeline under [\AKS\telescope](https://dev.azure.com/msazure/CloudNativeCompute/_build?definitionScope=%5CAKS%5Ctelescope) folder and trigger it using your own branch. To trigger, click the `Run pipeline` button in top right corner, then choose your branch under drop down menu under `Branch/tag` and click `Run` button in the bottom right corner.

For example, the pipeline for `vm-lb-vm-same-zone-iperf2.yml` is [Performance Evaluation VM-LB-VM Cross VNet Same Zone iPerf](https://dev.azure.com/msazure/CloudNativeCompute/_build?definitionId=338133).

### CI checks

We currently have 3 CI checks in place for GitHub Workflows:

* [Terraform Validate](https://github.com/Azure/telescope/actions/workflows/terraform-validate.yml): this one performs a dry run of the terraform code to validate that the `hcl` format and syntax is correct. It's triggered automatically when a PR is created or updated based on the changes in the PR.
  * To run the local format check run  this command `terraform fmt --check -recursive --diff`
  * To run local validation check run this command in respective terraform cloud modules folders 
    ```
    terraform init
    terraform validate
    ```
* [Terraform Plan](https://github.com/Azure/telescope/blob/main/.github/workflows/terraform-plan.yml): This workflow creates terraform plan for all the tests scenarios to make sure all terraform inputs are provided properly and check all required inputs for a test scenario. It's triggered automatically when a PR is created or updated based on the test scenario changes in the PR.
* [Python Unit Tests](https://github.com/Azure/telescope/actions/workflows/python-unit-tests.yml): this one runs the unit tests for all `py` related files to make sure python code is tested and validated. It's triggered automatically when a PR is created or updated based on the changes in the PR.
  * To run the tests locally, you can run the `python -m unittest discover` command in the python module folder of the repository.


# GitHub tag Scenarios:
- Sample github tag looks like this v1.0.32 which represents Version<MAJOR>.<MINOR>.<PATCH>
- Github changes are categorized in three types.
  1. Major
  2. Minor
  3. Patch
- Please check the current version used and increment the tag version based on the following scenarios.

## Current Tag version

| Current Version   | Major | Minor | Patch |
|-------------------|-------|-------|-------|
| V1.0.32           | 1     | 0     | 32    |


## Update Tag version based on the code changes
| Code Changes                   | Major | Minor | Patch | Example |
|----------------------------|-------|-------|-------|-------|
| Major Refactoring(Terraform)|&check;|&cross;|&cross;| v2.0.0|
| Specific Test Scenario    |&cross;|&cross;|&check;| v2.0.1|
| Engine-related Changes(Iperf,Jmeter)   |&cross;|&check;|&cross;| v2.1.0|
| Results data format updated |&cross;|&check;|&cross;| v2.2.0|
| Results data format remains same|&cross;|&cross;|&check;|v2.2.1|
| Interface change |&cross;|&check;|&cross;|v2.3.0|

Note:
 - Here Example version is based on the current version tag.
 - All the GitHub Version tags are found [here](https://github.com/Azure/telescope/tags)

## Cases to update tables and data connections.
- After the github version tag is updated. Please check the below table to identify what changes has to be done for the tables and data connection.

| Cases                   | Major | Minor | Patch |
|----------------------------|-------|-------|-------|
| New Tables                 |&check;|&check;|&cross;|
| New Data Connections      |&check;|&check;|&cross;|
| Update Existing Data connections     |&cross;|&cross;|&check;|

- To create new tables, data connections and Data ingestion use these pipelines.
  1. [System Database Table and Data Connection Creation](https://msazure.visualstudio.com/CloudNativeCompute/_build?definitionId=345697)
  2. [System Data Ingestion from Blob Storage](https://msazure.visualstudio.com/CloudNativeCompute/_build?definitionId=342761)
  3. Here is the [Readme](./modules/terraform/azure/onboarding/data-connection/Readme.md) on how to use these Pipelines.

## References

* [GitHub Workflows](https://docs.github.com/en/actions/using-workflows)
* [Azure Pipelines - Key Concept](https://learn.microsoft.com/en-us/azure/devops/pipelines/get-started/key-pipelines-concepts?view=azure-devops)
* [Terraform Fmt command](https://developer.hashicorp.com/terraform/cli/commands/fmt)
* [Terraform validate command](https://developer.hashicorp.com/terraform/cli/commands/validate)
* [Python Unit Tests](https://docs.python.org/3/library/unittest.html)
