azure_devops_config = {
	project_name = "telescope"
	#variable_groups = [ "Telescope Storage Account" ]
	variables = [
		{
			name = "AKS_TELESCOPE_ACCOUNT_NAME"
			value = "akstelescope"
		},
		{
			name = "AZURE_STORAGE_SUBSCRIPTION"
			value = "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"
		},
		{
			name = "AZURE_SUBSCRIPTION_ID"
			value = "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"
		},
		{
			name = "AWS_SERVICE_CONNECTION"
			value = "AWS-for-Telescope"
		},
		{
			name = "AZURE_SERVICE_CONNECTION"
			value = "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"
		}]
	pipeline_config = {
		name = "API Server Benchmark Virtual Nodes 10 Pods 100"
		path = "\\"
		repository = {
			repo_type = "GitHub"
			repository_name = "Azure/telescope"
			branch_name = " sumanth/pipeline-script"
			yml_path = "pipelines/perf-eval/apiserver-benchmark-virtualnodes10-pods100.yml"
			service_connection_name = "Telescope GH"
		}
		agent_pool_name = "Azure Pipelines"
	}
	service_connections = ["AWS-for-Telescope", "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"]
}