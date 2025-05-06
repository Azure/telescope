import os
from dataclasses import dataclass
from resource.setup import Setup

import yaml
from components import Cloud, Engine, Resource
from pipeline import Job, Pipeline, Stage, customize_yaml
from terraform.terraform import Terraform


@dataclass
class Layout:
    display_name: str
    cloud: Cloud
    resources: list[Resource]
    engine: Engine
    terraform: Terraform = None
    setup: Resource = None

    def __post_init__(self):
        if self.terraform is None:
            self.terraform = Terraform(
                cloud=self.cloud.cloud,
                regions=self.cloud.regions,
                credential_type=self.cloud.credential_type,
            )
        if self.setup is None:
            self.setup = Setup(
                run_id=os.getenv("RUN_ID"),
                cloud=self.cloud.cloud,
                regions=self.cloud.regions,
                engine=self.engine.type,
            )

    def get_jobs(self) -> list[Job]:

        setup = Job(
            job="setup",
            display_name="Setup resources",
            steps=self.setup.setup()
            + self.cloud.login()
            + [step for r in self.resources for step in r.setup()]
            + self.terraform.setup()
            + [
                self.terraform.create_resource_group(),
                self.terraform.run_command(command="version"),
                self.terraform.run_command(command="init"),
                self.terraform.run_command(command="apply"),
            ]
            + self.engine.setup(),
        )

        validate = Job(
            job="validate",
            display_name="Validate resources",
            steps=self.setup.validate()
            + [step for r in self.resources for step in r.validate()]
            + self.engine.validate(),
            depends_on=[setup.job],
        )
        run = Job(
            job="run",
            display_name="Run the benchmark",
            steps=self.engine.run(),
            depends_on=[validate.job],
        )
        tear_down = Job(
            job="tear down",
            display_name="Tear down resources",
            # Tears down in reverse order of setup.
            steps=self.engine.tear_down()
            + [step for r in self.resources[::-1] for step in r.tear_down()],
            depends_on=[run.job],
        )
        return [
            setup,
            validate,
            run,
            tear_down,
        ]


class Storage:
    pass


@dataclass
class Benchmark:
    name: str
    layouts: list[Layout]
    storage: Storage

    @staticmethod
    def get_yaml_path(file_path: str) -> str:
        relative_path = os.path.relpath(
            file_path, os.path.join(os.getcwd(), "pipelines")
        )
        yaml_file_path = os.path.join("generated", relative_path[:-3] + ".yaml")
        return yaml_file_path

    @staticmethod
    def prepare_directory(file_path: str):
        directory, _ = os.path.split(file_path)
        os.makedirs(directory, exist_ok=True)

    def write(self, file_path: str):
        stages = []
        for layout in self.layouts:
            stages.append(
                Stage(
                    display_name=layout.display_name,
                    jobs=layout.get_jobs(),
                )
            )
        p = Pipeline(stages=stages)

        yaml_file_path = self.get_yaml_path(file_path)
        self.prepare_directory(yaml_file_path)

        customize_yaml()
        with open(yaml_file_path, "w", encoding="utf-8") as file:
            yaml.dump(p, file, sort_keys=False)
