# Contribute a Test Scenario

## Step 1: Add Test Setup

- [scenarios](../scenarios) is the directory where we organize infrastructure setup for different tests. There are 2 type of scenarios: `perf-eval` and `issue-repro`. Most tests fall under the scenario type of `perf-eval`. 
- Create a folder for your test under [scenarios/perf-eval](../scenarios/perf-eval). The folder name should match values of `SCENARIO_TYPE` and `SCENARIO_NAME`, which is used in the pipeline definition YAML file. The `SCENARIO_NAME` should be within 30 characters.
- Your folder should contain 2 subfolders:
    - `terraform-inputs`: contains `.tfvars` file to specify how to set up resources
    - `terraform-test-inputs`: contains `.json` file to used in validating Terraform custom input
- Specific details on what to put in `.tfvars` file can be found in folder [terraform](../modules/terraform) for corresponding provider.

## Step 2: Add Python folder for new testing tools

- We encourage users to re-use or expand upon existing Python modules for your test if possible. All existing test engine can be found under folder [python](../modules/python/) folder.
- If you need to add a new test engine, create a new folder under [python](../modules/python/) and implement your test logic there. You can refer to existing engines for examples.
- If you want to use an existing test engine.
   * Without any change, you can skip this step.
    * With customization the existing test engine, you can go the corresponding folder under [python](../modules/python/) and modify the code as needed by expanding the parameters or logic in a way that doesn't break existing tests. Make sure to test your changes locally before using it in the pipeline.

## Step 3: Add Test Engine YAML files corresponding to your Python module

- We highly encourage re-using or extending the existing Engine files for new test cases if possible. All existing test engines can be found under the folder  [engine](../steps/engine). If you need to add a new test engine, you need to implement it under the folder [engine](../steps/engine) so it can be used in the pipeline definition YAML file.
- 
## Step 4: Add Test Topology

- It is also preferable to re-use the existing test topologies, but if none of the existing topology meets your need, or you want to customize the topology to be used with an existing test engine, you can create your own subfolder under [topology](../steps/topology/)
- Each folder under `topology` requires at least 3 files:
  - `validate-resources`
  - `execute-<engine>`
  - `collect-<engine>`

## Step 4: Add Pipeline Definition

- Add the pipeline definition to [new-pipeline-test.yml](../pipelines/system/new-pipeline-test.yml) in your private branch. This step is required and must not be skipped.
- Then verify the changes based on instructions in [verify.md](../docs/verify.md)
- Iterate until all verification setups pass without error, finally create a separate yaml file under a subfolder under [pipelines](../pipelines/perf-eval) based on test category. Move the content of the new-pipeline-test.yml to this new file and undo all changes made to the new-pipeline-test.yml file. It is recommended to re-use existing test categories as follows:

* [API Server & ETCD Benchmark](pipelines/perf-eval/API%20Server%20Benchmark)
* [Scheduler & Controller Benchmark](pipelines/perf-eval/Scheduler%20Benchmark)
* [Autoscaler/Karpenter Benchmark](pipelines/perf-eval/Autoscale%20Benchmark)
* [Container Network Benchmark](pipelines/perf-eval/CNI%20Benchmark)
* [Container Storage Benchmark](pipelines/perf-eval/CSI%20Benchmark/)
* [Container Runtime Benchmark](pipelines/perf-eval/CRI%20Benchmark/)
* [GPU/HPC Benchmark](pipelines/perf-eval/GPU%20Benchmark)
