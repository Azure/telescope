import os
from terraform.resource_group import ResourceGroup
from resource.python3 import Python3
from resource.setup import Setup
from resource.ssh import SSH

from benchmark import Benchmark, Layout
from cloud.azure import Azure
from engine.clusterloader2 import ClusterLoader2
from terraform.terraform import Terraform


def main():
    # TODO : Refactor, make function to generate layout
    azure_eastus2 = Azure(
        region="eastus2"
    )
    job_scheduling = Benchmark(
        name="job_scheduling",
        layouts=[
            Layout(
                display_name="azureeastus2",
                cloud=azure_eastus2,
                setup=Setup(run_id=os.getenv("RUN_ID")),
                resources=[
                    ResourceGroup(region="eastus2", scenario_name="job-scheduling"),
                    Terraform(
                        cloud=azure_eastus2,
                        regions=["eastus2"],
                        scenario_name="job-scheduling",
                    ),
                    Python3(),
                    SSH(cloud="azure")
                ],
                engine=ClusterLoader2(),
            )
        ],
        storage=None,
    )
    job_scheduling.write(__file__)


if __name__ == "__main__":
    main()
