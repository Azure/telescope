import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import lib.steps.azure

output = ap.Pipeline {
    name = "Example Pipeline"

    trigger =  ["v2"]
    pool = "AKS-Telescope-Ubuntu-EastUS2"

    jobs = [
        job.Job {
            job = "deploy_to_azure"
            displayName = "Deploy to Azure"

            steps = azure.Login(
                "Azure-for-Telescope-internal",
                "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248",
                "eastus"
            ) 
        }
    ]
}
