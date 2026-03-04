import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.const
import lib.steps.azure

output = ap.Pipeline {
    name = "Example Pipeline"

    trigger =  ["v2"]
    pool = const.DEFAULT_POOL

    jobs = [
        job.Job {
            job = "deploy_to_azure"
            displayName = "Deploy to Azure"

            steps = [
                azure.Login(
                    "b8ceb4e5-f05b-4562-a9f5-14acb1f24219",
                    "westus2"
               )
            ]
        }
    ]
}
