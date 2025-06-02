from dataclasses import dataclass
from pypeline.benchmark import Cloud
from pypeline.pipeline import Script


# This is for handling cloud resources at terraform
@dataclass
class CloudResource:
    cloud: Cloud

    def delete_resources(self) -> Script:
        pass
            
    def create_resource_group(self) -> Script:
        pass
    
    def delete_resource_group(self) -> Script:
        pass
    
    