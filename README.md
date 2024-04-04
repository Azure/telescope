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
└── issue-repo
    └── lb-tls-error
        ├── bash-scripts
        ├── https
        ├── terraform-inputs
        ├── terraform-test-inputs
        └── Makefile
    └── perf-eval
        └── vm-iperf
            ├── bash-scripts
            ├── terraform-inputs
            └── terraform-test-inputs
.gitignore
```
Here 

```
.github
└── workflows # List of CI workflows that runs for GH PR's
modules # Contains python/bash/Terraform modules related to files
├── bash # Script that are used of test scenarios
├── python # Python files that are used for different test scenarios
└── terraform # Terraform code for creating and managing infrastructure as code for AWS & Azure
    ├── aws
    └── azure
scenarios # All Scenario Types use for testing
└── issue-repo # One of the Scenario Type
    └── lb-tls-error # Scenario Name
        ├── bash-scripts
        ├── https
        ├── terraform-inputs
        ├── terraform-test-inputs
        └── Makefile
└── perf-eval # Another Scenario Type
    └── vm-iperf # Scenario Name
        ├── bash-scripts  # Place scripts required for this test scenario in this folder
        ├── terraform-inputs # tfvars that are used to create infrastrcuture for this test scenario.
        └── terraform-test-inputs  # Test inputs to verify tfvars input properly.
.gitignore # file that are ingored from checking into GitHub.
```


## Create and run Test Scenarios

### Test Scenarios

* All existing test scenarios are located in the [Azure\telescope](https://github.com/Azure/telescope/tree/main/scenarios) folder.
* 

### Build a new test scenario

#### Main workflows

* Step 1: create a test branch with new test scenario(vm-diff-zone-iperf) in [Azure/telescope](https://github.com/Azure/telescope/tree/main/scenarios) repository.
* Step 2: 

**Template:**

```yaml
trigger: none

schedules:
  - cron: <cron-syntax-schedule>
    displayName: <schedule-name>
    branches:
      include:
        - main
    always: true

variables:
  SCENARIO_REPO: Azure/telescope # must keep as is
  SCENARIO_TYPE: <scenario-type> 
  SCENARIO_NAME: <scenario-name>
  SCENARIO_VERSION: <Azure/telescope branch, tag, or SHA>

pool:
  name: <agent-pool-name>

stages:
  - stage: <stage-name> # format: <cloud>[_<region>]+ (e.g. azure_eastus2, aws_eastus_westus)
    dependsOn: []
    jobs:
      - template: /jobs/competitive-test.yml # must keep as is
        parameters:
          cloud: <cloud> # e.g. azure, aws
          regions: # list of regions
            - region1 # e.g. eastus
            - region2 # e.g. westus
          topology: <topology> # e.g. vm-lb-vm
          engine: <engine> # e.g. iperf2
          matrix: # list of test parameters to customize the provisioned resources
            <case-name>:
              <key1>: <value1>
              <key2>: <value2>
          max_parallel: <number of concurrent jobs> # required
          timeout_in_minutes: <timeout in minutes> # if not specified, default is 60
```

* Step 3: trigger the pipeline [New Pipeline Test](https://dev.azure.com/msazure/CloudNativeCompute/_build?definitionId=338871) to run your test. To trigger, click the `Run pipeline` button in top right corner, then choose your branch under drop down menu under `Branch/tag` and click `Run` button in the bottom right corner.
* Step 4: once you verify the new test is working properly, create a new pipeline `yml` file under `pipelines` folder and in the corresponding subfolder depending on your test type (`perf-eval` or `issue-repro`). Move the content of the `new-pipeline-test.yml` to this new file and undo all changes made to the `new-pipeline-test.yml` file.
* Step 5: create a new pull request to merge the new pipeline `yml` file to the main branch and ask owner to create a new pipeline for you once the PR is merged.

#### Template explanation

* `trigger`: we only run test based on schedules so `none` is used here to avoid unnecessary runs when changes are made to the pipeline file.
* `schedules`: we use this to define the schedule of test run. The [cron syntax](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/scheduled-triggers?view=azure-devops&tabs=yaml) is used to define the schedule in `cron` section. Note that schedule is in UTC time zone. Example

```yaml
schedules:
  - cron: "0 */2 * * *"
    displayName: "Daily even hours"
    branches:
      include:
        - main
    always: true
```

* `pool`: currently, we have 2 agent pools available for general use. Note that they are all Linux agents using Ubuntu 22.04
  * [1ES-Telescope-Local-Debug-EastUS](https://dev.azure.com/msazure/CloudNativeCompute/_settings/agentqueues?queueId=181842&view=jobs): for manual testing
  * [1ES-Telescope-Ubuntu-EastUS](https://dev.azure.com/msazure/CloudNativeCompute/_settings/agentqueues?queueId=184798&view=jobs): for scheduled runs

Example usage:

```yaml
pool:
  name: "1ES-Telescope-Local-Debug-EastUS"
```

* `variables`: we use these variables to define which test scenario we want to check out from the `Azure/telescope` repository. Suppose you define a new test in a folder called `my-new-test` under [`perf-eval`](https://github.com/Azure/telescope/tree/main/scenarios/perf-eval) folder and the branch that you use to write the test is `my-test-branch`, then the variables should have the following values:

```yaml
variables:
  SCENARIO_REPO: Azure/telescope
  SCENARIO_TYPE: perf-eval
  SCENARIO_NAME: my-new-test
  SCENARIO_VERSION: my-test-branch
```

* `stages`: each stage represents a test run for a specific cloud in specific region(s) depending on whether your cloud resources are all in one region or spread across regions.

For example:

* If your test is for Azure and all resources are in East US 2, then you can use the following stage definition:

```yaml
  - stage: azure_eastus2
    dependsOn: []
    jobs:
      - template: /jobs/competitive-test.yml
        parameters:
          cloud: azure
          regions:
            - eastus2
```

* If your test is for AWS and resources are in US East and US West, then you can use the following stage definition:

```yaml
  - stage: aws_eastus_westus
    dependsOn: []
    jobs:
      - template: /jobs/competitive-test.yml
        parameters:
          cloud: aws
          regions:
            - us-east-1
            - us-west-1
```

**Note**: Each cloud have a different way of naming regions so make sure to use the correct region name for the cloud you are testing. If you want to run the same test for multiple regions, then you should define multiple stages for each region. The `regions` parameter should only contain more than 1 value if for that test, resources are spread across regions.

* `topology`: refers to the setup of your resources. Based on different setups, the validation, execution, and collection of a test will be implemented differently. You can either re-use an [existing topology](steps/topology/) or define a new one if none of them fits your test.

Example: for a test  with a setup 2 VMs and an ILB in between, you can define the topology as follows

```yaml
topology: vm-ilb-vm
```

* `engine`: refers to the tool you use to run your test. Each tool has its own way of running and collecting results. You can either re-use an [existing engine](steps/engine/) or define a new one if none of them fits your needs.

Example: for test that uses iperf2, the engine is defined as below

```yaml
engine: iperf2
```

* `matrix`: refers to the customization of resources. For example, if you want to run the same test on different Azure VM sizes, then you can define the matrix as follows:

```yaml
matrix:
  v3_without_accel_net:
    machine_type: Standard_D16_v3
    accelerated_networking: "false"
  v3_with_accel_net:
    machine_type: Standard_D16_v3
    accelerated_networking: "true"
  v5_with_accel_net:
    machine_type: Standard_D16_v5
    accelerated_networking: "true"
```

*Note*: For the list of what parameters you can customize based on clouds, refer to [set-input-variables-aws](steps/terraform/set-input-variables-aws.yml) for AWS and [set-input-variables-azure](steps/terraform/set-input-variables-azure.yml) for Azure. These are where you need to update if you add new inputs ([Azure](https://github.com/Azure/telescope/blob/main/modules/terraform/azure/variables.tf) and [AWS](https://github.com/Azure/telescope/blob/main/modules/terraform/aws/variables.tf)) to Terraform in `Azure/telescope` repository.

* `max_parallel`: refers to the number of concurrent jobs you want to run. This is to avoid overloading the agent pool. Each value in `matrix` corresponds to a job. The number of parallel jobs should always be less than or equal to the number of values in `matrix`. In the example above, we have 3 values in `matrix` so the `max_parallel` should be less than or equal to 3.
* `timeout_in_minutes`: refers to the maximum time a job can run. When that time is reached, job will be cancelled immediately. Thus, it's important that you set the right value taking into account the runtime of all steps: setup, provision, validate, execute, collect, cleanup. If not specified, the default value is 60 minutes.

### Update an existing test/pipeline

* Step 1: create a test branch in [Azure/telescope](https://github.com/Azure/telescope/tree/main/scenarios) repository.
* Step 2: navigate to the pipeline file you want to update and make the necessary changes. You can coordinate using `SCENARIO_TYPE` and `SCENARIO_NAME` to find the corresponding pipeline file.

For example, if you want to update the [lb-same-zone-iperf](https://github.com/Azure/telescope/tree/main/scenarios/perf-eval/lb-same-zone-iperf), then you should navigate to the [vm-lb-vm-same-zone-iperf2.yml](pipelines/perf-eval/vm-lb-vm-same-zone-iperf2.yml) file.

* Step 3: update `SCENARIO_VERSION` to the branch/tag/SHA of where you change is.

For example, if your branch name is `my-name/update-lb-iperf2` in `Azure/telescope`, then you should update `SCENARIO_VERSION` to `my-name/update-lb-iperf2`.

* Step 4: navigate to the corresponding pipeline under [\AKS\telescope](https://dev.azure.com/msazure/CloudNativeCompute/_build?definitionScope=%5CAKS%5Ctelescope) folder and trigger it using your own branch. To trigger, click the `Run pipeline` button in top right corner, then choose your branch under drop down menu under `Branch/tag` and click `Run` button in the bottom right corner.

For example, the pipeline for `vm-lb-vm-same-zone-iperf2.yml` is [Performance Evaluation VM-LB-VM Cross VNet Same Zone iPerf](https://dev.azure.com/msazure/CloudNativeCompute/_build?definitionId=338133).

### CI checks

We currently have 2 CI checks in place for pipelines:

* [System YAML Syntax Checker](https://dev.azure.com/msazure/CloudNativeCompute/_build?definitionId=354326&_a=summary): this one performs a dry run of the pipeline to validate that the `yaml` syntax is correct. It's triggered automatically when a PR is created or updated.
  * If you think your yaml syntax is correct, but still see errors like **file not found** or **unexpected parameter**, it might be because your branch is out of sync with the main branch. In this case, you can resolve the issue by getting the latest changes from the `main` branch.
* [System YAML Linter](https://dev.azure.com/msazure/CloudNativeCompute/_build?definitionId=354326&_a=summary): this one performs a lint check all `yaml` files to make sure format is consistent and follows the best practices. It's triggered automatically when a PR is created or updated.
  * To examine the lint errors locally, you can install the `yamllint` package using `pip install yamllint` and run `yamllint -c .yamllint . --no-warnings` in the root of the repository.
  * The fastest way to fix lint errors in a file is to install this extension [YAML - Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) in VSCode and format the file with it.

## References

* [YAML schema](https://learn.microsoft.com/en-us/azure/devops/pipelines/yaml-schema/?view=azure-pipelines)
* [Azure Pipelines - Key Concept](https://learn.microsoft.com/en-us/azure/devops/pipelines/get-started/key-pipelines-concepts?view=azure-devops)
* [1ES Hosted Pools](https://eng.ms/docs/cloud-ai-platform/devdiv/one-engineering-system-1es/1es-docs/1es-hosted-azure-devops-pools/onboarding-overview)
* [Pre-installed Software in 1ES Hosted Pools](https://learn.microsoft.com/en-us/azure/devops/pipelines/agents/hosted?view=azure-devops&tabs=yaml#software)
