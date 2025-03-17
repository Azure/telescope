# Pypeline

Previously Telescope was built using YAML and YAML templates. However YAML has the following problems.

- It's repetitive to write.
- There is no "go-to-definition" of a YAML template or find where they are referenced in an IDE, like VSCode.
- It describes how the pipelines work rather than how the benchmarks work.
- When creating a new pipeline, it still requires a fair bit of copying of an existing pipeline.

Pypeline was created to solve this. Pypeline builds on two simple ideas.

1. The users should be agnostic to piplines. They just need to define the benchmark. E.g. what resources to create, what engine to run. The plumbing of pipelines are left to the implementation.
1. Use Python to model a benchmark, then write it to a YAML file that Azure pipeline can consume.

## Write a new benchmark

### Describe your benchmark

Write a Python file in the `pipelines` folder, that instanciates the Benchmark class.
Check out `pipelines/controller/job_scheduling.py` as an example.

### Generate your pipeline yaml

Here's an example to generate the `job_scheduling.yaml`.

```bash
cd pypeline
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 pipelines/controller/job_scheduling.py
```
The yaml is created under the correcpoding folder under `generated`. E.g. `pipelines/controller/job_scheduling.py` will generate the yaml file of `generated/controller/job_scheduling.yaml`


### Configure debugger in VSCode
To use the Python debugger in VSCode, you need to update your debugger configuration, A.K.A. `.vscode/launch.json` file, as follows.

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python Debugger: Current File",
            "type": "debugpy",
            "request": "launch",
            "program": "${file}",
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}/pypeline",
            "env": {
                "PYTHONPATH": "${workspaceFolder}/pypeline",
            }
        }
    ]
}
```
