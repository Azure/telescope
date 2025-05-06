from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from pipeline import Step

# Keep components here to avoid circular imports


class CredentialType(Enum):
    MANAGED_IDENTITY = "managed_identity"
    SERVICE_CONNECTION = "service_connection"

@dataclass
class Resource(ABC):
    cloud: str
    regions: list[str]

    @abstractmethod
    def setup(self) -> list[Step]:
        pass

    @abstractmethod
    def validate(self) -> list[Step]:
        pass

    @abstractmethod
    def tear_down(self) -> list[Step]:
        pass


# Factory class to create resources:
# To avoid repeatedly define shared properties for every resource. usage: @ job_scheduling.py
@dataclass
class ResourceFactory:
    cloud: str
    regions: list[str]

    def create(self, resource_class, **kwargs):
        return resource_class(cloud=self.cloud, regions=self.regions, **kwargs)

@dataclass
class Engine(Resource):
    type: str

    @abstractmethod
    def run(self) -> list[Step]:
        pass

@dataclass
class Cloud(ABC):
    cloud: str
    regions: list[str]
    credential_type: str

    @abstractmethod
    def login(self) -> list[Step]:
        pass
