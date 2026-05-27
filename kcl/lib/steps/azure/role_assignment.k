import azure_pipelines.ap.steps

CreateRoleAssignment = lambda serviceConnection: str, scope: str, role: str, assignee: str, subscription: str -> steps.Step {
    script = """
az role assignment create \\
  --scope "${scope}" \\
  --role "${role}" \\
  --assignee "${assignee}" \\
  --subscription "${subscription}"
"""
    AzCli(serviceConnection, "Assign role ${role}", script)
}
