import azure_pipelines.ap.steps
import lib.steps.azure

UploadResult = lambda serviceConnection: str, storageAccount: str, subscription: str, container: str, localFile: str = "/tmp/run-result.json" -> steps.Step {
    azure.AzCli(
        serviceConnection,
        "Upload result to storage account",
        """
az storage blob upload \\
  --account-name "${storageAccount}" \\
  --subscription "${subscription}" \\
  --container-name "${container}" \\
  --name "$(RUN_ID)/run-result.json" \\
  --file ${localFile} \\
  --auth-mode key
""")
}
