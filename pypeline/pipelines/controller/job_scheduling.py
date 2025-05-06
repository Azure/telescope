from resource.python3 import Python3
from resource.ssh import SSH

from benchmark import Benchmark, Layout
from cloud.azure import Azure
from components import ResourceFactory
from engine.clusterloader2 import ClusterLoader2


def main():
    cloud_az_eastus2 = Azure(regions=["eastus2"])

    # Resource Factory: to avoid repeatedly defining same attributes for every new resources
    resource_factory = ResourceFactory(
        cloud=cloud_az_eastus2.cloud, regions=cloud_az_eastus2.regions
    )
    # Define the resources
    resources = [
        resource_factory.create(Python3),
        resource_factory.create(SSH),
    ]
    cl2_engine = resource_factory.create(ClusterLoader2)

    # Define test layout
    azure_east_us2 = Layout(
        display_name="Job Scheduling",
        cloud=cloud_az_eastus2,
        resources=resources,
        engine=cl2_engine,
    )

    job_scheduling = Benchmark(
        name="job_scheduling",
        layouts=[azure_east_us2],
        storage=None,
    )
    job_scheduling.write(__file__)


if __name__ == "__main__":
    main()
