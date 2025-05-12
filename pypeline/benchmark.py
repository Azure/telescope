import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import yaml

from pipeline import Job, Pipeline, Stage, Step, customize_yaml


class CloudProvider(Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


class Resource(ABC):
    @abstractmethod
    def setup(self) -> list[Step]:
        pass

    @abstractmethod
    def validate(self) -> list[Step]:
        pass

    @abstractmethod
    def tear_down(self) -> list[Step]:
        pass


class Engine(Resource):
    @abstractmethod
    def run(self) -> list[Step]:
        pass


class Cloud(ABC):
    @property
    @abstractmethod
    def provider(self) -> CloudProvider:
        pass

    @abstractmethod
    def login(self) -> list[Step]:
        pass

    @abstractmethod
    def generate_input_variables(self, region: str, input_variables: dict) -> dict:
        pass

    @abstractmethod
    def delete_resource_group(self) -> str:
        pass

    @abstractmethod
    def create_resource_group(self) -> str:
        pass


@dataclass
class Layout:
    display_name: str
    setup: Resource
    cloud: Cloud
    resources: list[Resource]
    engine: Engine

    def get_jobs(self) -> list[Job]:
        setup = Job(
            job="setup",
            display_name="Setup resources",
            steps=self.setup.setup()
            + self.cloud.login()
            + [step for r in self.resources for step in r.setup()]
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
