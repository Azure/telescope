import os
from resource.python3 import Python3
from resource.setup import Setup

from benchmark import Benchmark, Layout
from cloud.azure import Azure
from engine.clusterloader2 import ClusterLoader2
from resource.terraform.terraform import Terraform

def main():
    cloud_az_eastus2 = Azure(region="eastus2")
    azure_east_us2 = Layout(
        display_name="Job Scheduling",
        setup=Setup(run_id=os.getenv("RUN_ID")),
        cloud=cloud_az_eastus2,
        resources=[
            Python3(),
            Terraform(cloud_obj=cloud_az_eastus2),  # Dynamically retrieve cloud from layout
        ],
        engine=ClusterLoader2(),
    )

    job_scheduling = Benchmark(
        name="job_scheduling",
        layouts=[azure_east_us2
                ],
        storage=None,
    )
    job_scheduling.write(__file__)


if __name__ == "__main__":
    main()
