import os
from resource.python3 import Python3
from resource.setup import Setup
from resource.ssh import SSH

from benchmark import Benchmark, Layout
from cloud.azure import Azure
from engine.clusterloader2 import ClusterLoader2
from terraform.resource_group import ResourceGroup
from terraform.terraform import Terraform


def main():
    # TODO : Refactor, make function to generate layout
    az_regions = ["eastus2"]
    az_scenario_name = "job-scheduling"
    az_deletion_delay = "1h"
    az_cloud = Azure(region=az_regions[0])
    job_scheduling = Benchmark(
        name="job_scheduling",
        layouts=[
            Layout(
                display_name="azureeastus2",
                cloud=az_cloud,
                setup=Setup(run_id=os.getenv("RUN_ID")),
                resources=[
                    ResourceGroup(
                        region=az_regions[0],
                        scenario_name=az_scenario_name,
                        deletion_delay=az_deletion_delay,
                    ),
                    Terraform(
                        cloud=az_cloud,
                        regions=az_regions,
                        scenario_name=az_scenario_name,
                    ),
                    Python3(),
                    SSH(cloud=az_cloud.provider),
                ],
                engine=ClusterLoader2(),
            )
        ],
        storage=None,
    )
    job_scheduling.write(__file__)


if __name__ == "__main__":
    main()
