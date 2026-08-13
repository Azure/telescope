import azure_pipelines.ap
import azure_pipelines.ap.jobs.job
import azure_pipelines.ap.steps
import lib.const
import lib.steps.aks_flex
import lib.steps.azure
import lib.steps.common

CONFIG_ARGS = """
--set runId=$(RUN_ID) \\
--set subscriptionId=\${{ parameters.subscriptionId }} \\
--set aksRegion=\${{ parameters.aksRegion }} \\
--set vmRegion=\${{ parameters.vmRegion }} \\
--set flexVmSize=\${{ parameters.flexVmSize }} \\
--set bootstrapMode=\${{ parameters.bootstrapMode }} \\
--set nodeCount=\${{ parameters.nodeCount }} \\
--set vmCreateConcurrency=\${{ parameters.vmCreateConcurrency }} \\
--set vmCreateBatchSize=\${{ parameters.vmCreateBatchSize }} \\
--set vmBatchDeploymentConcurrency=\${{ parameters.vmBatchDeploymentConcurrency }} \\
--set aksKubernetesVersion=\${{ parameters.aksKubernetesVersion }} \\
--set aksFlexNodeVersion=\${{ parameters.aksFlexNodeVersion }} \\
--set unboundedVersion=\${{ parameters.unboundedVersion }}
"""

output = ap.Pipeline {
    name = "AKS Flex Node 1K Join Scale"
    trigger = []
    pool = const.DEFAULT_POOL

    parameters = [
        ap.Parameter {name = "subscriptionId", displayName = "Azure subscription ID", type = "string", default = "854c9ddb-fe9e-4aea-8d58-99ed88282881"},
        ap.Parameter {name = "serviceConnection", displayName = "Azure service connection", type = "string", default = const.DEFAULT_SERVICE_CONNECTION},
        ap.Parameter {name = "aksRegion", displayName = "AKS region", type = "string", default = "canadacentral"},
        ap.Parameter {name = "vmRegion", displayName = "Flex VM region", type = "string", default = "canadacentral"},
        ap.Parameter {name = "flexVmSize", displayName = "Flex VM SKU (minimum 4 vCPU)", type = "string", default = "Standard_D4_v4"},
        ap.Parameter {name = "bootstrapMode", displayName = "Bootstrap source (local-config or rp)", type = "string", default = "local-config"},
        ap.Parameter {name = "nodeCount", displayName = "Flex node count", type = "number", default = 1000},
        ap.Parameter {name = "vmCreateConcurrency", displayName = "Concurrent VM create requests", type = "number", default = 50},
        ap.Parameter {name = "vmCreateBatchSize", displayName = "VM create batch size", type = "number", default = 100},
        ap.Parameter {name = "vmBatchDeploymentConcurrency", displayName = "Concurrent ARM VM batch deployments", type = "number", default = 2},
        ap.Parameter {name = "aksKubernetesVersion", displayName = "AKS version", type = "string", default = "latest"},
        ap.Parameter {name = "aksFlexNodeVersion", displayName = "AKS Flex Node version", type = "string", default = "latest"},
        ap.Parameter {name = "unboundedVersion", displayName = "Unbounded version", type = "string", default = "latest"},
        ap.Parameter {name = "retainOnFailure", displayName = "Retain environment when the test fails", type = "boolean", default = False},
        ap.Parameter {name = "retainEnvironment", displayName = "Always retain environment (debug only)", type = "boolean", default = False},
    ]

    jobs = [job.Job {
        job = "aks_flex_scale"
        displayName = "Provision and join AKS Flex Nodes"
        timeoutInMinutes = 360
        steps = [
            common.SetRunId(),
            azure.AzCli(
                "\${{ parameters.serviceConnection }}",
                "Initialize scale test",
                """
echo "##vso[task.setvariable variable=FLEX_TEST_FAILED]true"
mkdir -p "$(Pipeline.Workspace)/flex-scale"
"""),
            aks_flex.RunScaleCommand(
                "\${{ parameters.serviceConnection }}", "plan", "Plan scale test", CONFIG_ARGS),
            aks_flex.RunScaleCommand(
                "\${{ parameters.serviceConnection }}", "resolve", "Resolve latest versions", CONFIG_ARGS),
            aks_flex.RunScaleCommand(
                "\${{ parameters.serviceConnection }}", "preflight", "Run deterministic preflight", CONFIG_ARGS),
            aks_flex.RunScaleCommand(
                "\${{ parameters.serviceConnection }}", "provision", "Create AKS Flex environment", CONFIG_ARGS),
            aks_flex.RunScaleCommand(
                "\${{ parameters.serviceConnection }}", "prepare-vms", "Pre-create 1,000 Flex VMs", CONFIG_ARGS),
            aks_flex.RunScaleCommand(
                "\${{ parameters.serviceConnection }}", "join", "Run one-hour Flex join test", CONFIG_ARGS),
            aks_flex.RunScaleCommand(
                "\${{ parameters.serviceConnection }}", "validate", "Validate complete Flex fleet", CONFIG_ARGS),
            azure.AzCli(
                "\${{ parameters.serviceConnection }}",
                "Mark scale test successful",
                "echo \"##vso[task.setvariable variable=FLEX_TEST_FAILED]false\""),
            aks_flex.RunScaleCommand(
                "\${{ parameters.serviceConnection }}", "result", "Write Telescope result", CONFIG_ARGS,
                condition = "always()", continueOnError = True),
            azure.AzCli(
                "\${{ parameters.serviceConnection }}",
                "Upload Telescope result",
                """
if [ -s /tmp/run-result.json ]; then
  az storage blob upload \\
    --account-name "${const.DEFAULT_STORAGE_ACCOUNT}" \\
    --subscription "${const.DEFAULT_STORAGE_SUBSCRIPTION_ID}" \\
    --container-name "${const.DEFAULT_STORAGE_CONTAINER}" \\
    --name "$(RUN_ID)/run-result.json" \\
    --file /tmp/run-result.json \\
    --auth-mode key
else
  echo "No result file was produced" >&2
  exit 1
fi
""",
                condition = "always()", continueOnError = True),
            steps.Task {
                task = "PublishPipelineArtifact@1"
                inputs = {
                    targetPath = "$(Pipeline.Workspace)/flex-scale"
                    artifact = "aks-flex-scale-$(RUN_ID)"
                    publishLocation = "pipeline"
                }
                displayName = "Publish scale test state and events"
                condition = "always()"
                continueOnError = True
            },
            aks_flex.RunScaleCommand(
                "\${{ parameters.serviceConnection }}", "cleanup", "Delete scale-test resource groups", CONFIG_ARGS,
                condition = "and(always(), not(\${{ parameters.retainEnvironment }}), or(ne(variables['FLEX_TEST_FAILED'], 'true'), not(\${{ parameters.retainOnFailure }})))"),
        ]
    }]
}
