azure_devops_config = {
	project_name = "telescope"
	variable_groups_to_link = [ "Telescope Storage Account", "Telescope AWS Credentials", "Telescope Azure Credentials" ]
	pipeline_config = {
		name = "Telescope Pipeline"
		path = "\\"
		repository = {
			repo_type = "TfsGit "
			repository_name = "telescope"
			branch_name = "main"
			yml_path = "azure-pipelines.yml"
			service_connection_name = "telescope-github"
		}
		agent_pool_name = "Hosted Ubuntu 1604"
	}
}