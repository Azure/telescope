import os
from resource.python3 import Python3
from resource.setup import Setup
from resource.ssh import SSH

from benchmark import Benchmark, Layout
from cloud.azure import Azure
from engine.clusterloader2 import ClusterLoader2
from terraform.terraform import Terraform


def main():
    # TODO : Refactor, make function to generate layout
    azure_eastus2 = Azure(region="eastus2")
    job_scheduling = Benchmark(
        name="job_scheduling",
        layouts=[
            Layout(
                display_name="azure-eastus2",
                cloud=Azure(),
                setup=Setup(run_id=os.getenv("RUN_ID")),
                resources=[
                    Terraform(cloud=azure_eastus2, regions=["eastus2"]),
                    Python3(),
                    SSH(cloud="azure"),
                ],
                engine=ClusterLoader2(),
            )
        ],
        storage=None,
    )
    job_scheduling.write(__file__)


if __name__ == "__main__":
    main()
