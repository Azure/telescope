# Contribute a Test Scenario

## Step 1: Add Test Setup

- [scenarios](../scenarios) is the directory where we organize infrastructure setup for different tests. There are 2 type of scenarios: `perf-eval` and `issue-repro`. Most tests fall under the category of `perf-eval`.
- Create a folder for your test under [scenarios/perf-eval](../scenarios/perf-eval). Your folder name should match value of `SCENARIO_NAME`, which is used in the final yaml file.
- Your folder should contain 2 subfolders:
    - `terraform-inputs`: contains `.tfvars` file to specify how to set up resources
    - `terraform-test-inputs`: contains `.json` file to used in validating Terraform custom input
- Specific details on what to put in `.tfvars` file can be found in folder [terraform](../modules/terraform) for corresponding provider.

## Step 2: Add Test Tool

- We high encourage re-using or extending the existing Python modules for new test case if possible. All existing test engine can be found under folder [python](../modules/python). Then you need add a new test engine, you need to implement it under folder [engine](../steps/engine) so it can be used in pipeline definition yaml file.
- 
## Step 3: Add Test Engine and Topology

- It is also preferrable to re-use the existing test topologies, but if none of the existing topology meets your need, or you want to customize the topology to be used with an existing test engine, you can create your own subfolder under [topology](../steps/topology)
- Each folder under `topology` required at least 3 files:
  - `validate-resources`
  - `excute-<engine>`
  - `collect-<engine>`

## Step 4: Add Pipeline Definition

- Add the pipleine definition to [new-pipeline-test.yml](../pipelines/system/new-pipeline-test.yml) in your private branch.
- Then verify the changes based on instructions in [verify.md](../docs/verify.md)
- Iterate until all verification setups pass without error, finally create a separate yaml file under a subfolder under [pipelines](../pipelines/perf-eval) based on test category. Move the content of the new-pipeline-test.yml to this new file and undo all changes made to the new-pipeline-test.yml file. It is recommanded to re-use existing test categories as follows:

* [API Server & ETCD Benchmark](pipelines/perf-eval/API%20Server%20Benchmark)
* [Scheduler & Controller Benchmark](pipelines/perf-eval/Scheduler%20Benchmark)
* [Autoscaler/Karpenter Benchmark](pipelines/perf-eval/Autoscale%20Benchmark)
* [Container Network Benchmark](pipelines/perf-eval/CNI%20Benchmark)
* [Container Storage Benchmark](pipelines/perf-eval/CSI%20Benchmark/)
* [Container Runtime Benchmark](pipelines/perf-eval/CRI%20Benchmark/)
* [GPU/HPC Benchmark](pipelines/perf-eval/GPU%20Benchmark)
