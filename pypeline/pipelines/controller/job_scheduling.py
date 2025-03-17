import os
from resource.python3 import Python3
from resource.setup import Setup

from benchmark import Benchmark, Layout
from cloud.azure import Azure
from engine.clusterloader2 import ClusterLoader2


def main():
    job_scheduling = Benchmark(
        name="job_scheduling",
        layouts=[
            Layout(
                display_name="eastus",
                setup=Setup(run_id=os.getenv("RUN_ID")),
                cloud=Azure(),
                resouces=[
                    Python3(),
                ],
                engine=ClusterLoader2(),
            )
        ],
        storage=None,
    )
    job_scheduling.write(__file__)


if __name__ == "__main__":
    main()
