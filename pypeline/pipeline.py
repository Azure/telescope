from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Optional

import yaml

# The classes are modeled after https://learn.microsoft.com/en-us/azure/devops/pipelines/yaml-schema/pipeline?view=azure-pipelines.


@dataclass
class Step:
    pass


@dataclass
class Script(Step):
    display_name: str = field(metadata={"yaml": "displayName"})
    script: str
    condition: Optional[str] = field(metadata={"yaml": "condition"}, default=None)
    retryCountOnTaskFailure: Optional[int] = field(metadata={"yaml": "retryCountOnTaskFailure"}, default=None)
    env: Optional[dict[str, str]] = field(metadata={"yaml": "env"}, default=None)


@dataclass
class Task(Step):
    display_name: str = field(metadata={"yaml": "displayName"})
    task: str
    inputs: Optional[dict[str, str]] = None


@dataclass
class Strategy:
    max_parallel: int = field(metadata={"yaml": "maxParallel"})


@dataclass
class Job:
    job: str  # Required as first property. ID of the job.
    display_name: str = field(metadata={"yaml": "displayName"})
    steps: list[Step]
    depends_on: Optional[list[str]] = field(
        metadata={"yaml": "dependsOn"}, default=None
    )
    condition: Optional[str] = None
    continue_on_error: Optional[str] = field(
        metadata={"yaml": "continueOnError"}, default=None
    )
    timeout: Optional[datetime] = field(
        metadata={"yaml": "timeoutInMinutes"}, default=None
    )
    cancel_timeout: Optional[datetime] = field(
        metadata={"yaml": "cancelTimeoutInMinutes"}, default=None
    )
    variables: Optional[list[str]] = None
    strategy: Optional[Strategy] = None
    pool: Optional[str] = None
    container: Optional[str] = None
    services: Optional[dict] = None
    workspace: Optional[dict] = None
    uses: Optional[dict] = None


@dataclass
class Stage:
    display_name: str = field(metadata={"yaml": "displayName"})
    jobs: list[Job]
    depend_on: Optional[list[str]] = field(metadata={"yaml": "dependsOn"}, default=None)
    condition: Optional[str] = None
    variables: Optional[list[str]] = None
    is_skippable: Optional[bool] = field(metadata={"yaml": "isSkippable"}, default=None)


@dataclass
class Pipeline:
    stages: list[Stage]


def literal_block_representer(dumper: yaml.Dumper, data: str):
    if "\n" in data:
        data = "\n".join([line.rstrip() for line in data.splitlines()])  
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def custom_name_representer(dumper, data):
    data_dict = {}
    for field in fields(data):
        yaml_name = field.metadata.get("yaml", field.name)
        value = getattr(data, field.name)
        if value is not None:
            data_dict[yaml_name] = value
    return dumper.represent_dict(data_dict)


def customize_yaml():
    yaml.add_representer(str, literal_block_representer)
    yaml.add_representer(Pipeline, custom_name_representer)
    yaml.add_representer(Stage, custom_name_representer)
    yaml.add_representer(Job, custom_name_representer)
    yaml.add_representer(Strategy, custom_name_representer)
    yaml.add_representer(Task, custom_name_representer)
    yaml.add_representer(Script, custom_name_representer)
<<<<<<< HEAD


=======
>>>>>>> pypeline
