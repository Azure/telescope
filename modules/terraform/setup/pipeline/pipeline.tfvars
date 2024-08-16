azure_devops_config = {
	project_name = "telescope"
	variable_groups_to_link = [ "AKS Telescope Github"]
	pipeline_config = {
		name = "Telescope Test Pipeline "
		path = "\\"
		repository = {
			repo_type = "GitHub"
			repository_name = "Azure/telescope"
			branch_name = "sumanth/poc"
			yml_path = "test.yml"
			service_connection_name = "telescope"
		}
		agent_pool_name = "Azure Pipelines"
	}
}