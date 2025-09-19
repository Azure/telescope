# E2E Testing Guide

## What is E2E Testing?

E2E testing in Telescope runs performance benchmarks across cloud providers (Azure, AWS, GCP) using Azure DevOps pipelines to validate test scenarios. It runs all the key steps of the [Design](design.md) using current branch changes.

## Prerequisites

* [Node.js 20+](https://nodejs.org/en/download/) - Required for MCP Azure DevOps server
* [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) - For authentication
* Access to `akstelescope` Azure DevOps organization with `telescope` project
* For Claude users install the ADO MCP server:
Note: We need to restart session after installing the MCP server for claude to pick up the new server.
```
claude mcp add ado -- npx -y @azure-devops/mcp akstelescope
```
* Only for non-Claude users,
```
* Add ADO MCP server to your MCP configuration. Create a `.vscode/mcp.json` file in the root of 
your project with the following content:
```
{
  "inputs": [
    {
      "id": "ado_org",
      "type": "promptString",
      "description": "Azure DevOps organization name",
      "default": "akstelescope"
    }
  ],
  "servers": {
    "ado": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@azure-devops/mcp", "${input:ado_org}"]
    }
  }
}
```
* Start the MCP server.
* Authentication to Azure DevOps using device code authentication if user is not already authenticated (`az login --use-device-code`)

## Key Information

- Always use ["New Pipeline Test"](../pipelines/system/new-pipeline-test.yml) for running E2E tests

## How to Run E2E Test

### Step 1: Setup and Verify Connection
1. **Verify Connection**: Confirm the server is running and accessible by using `build_get_definitions` command to list available build definitions and ensure the connection is established. Also get the build definition ID for the "New Pipeline Test".

2. **Get Build Definition ID**: Use `build_get_definitions` to retrieve the build definition ID for the "New Pipeline Test" in the `telescope` project. This ID is required to trigger the build.
### Step 2: Trigger the ADO Build & Monitor Status

1. **Start Build**: Use `build_run_build` - Start the test with project name, definition ID, and source branch name
2. **Monitor Status**: Use `build_get_status` - Check the build status every 15 minutes  
3. **Retrieve Logs**: Use `build_get_log` - Retrieve error logs if the build fails
4. **Get Specific Logs**: Use `build_get_log_by_id` - Get logs for a specific build log by log ID if the build fails


## Common Issues in E2E Testing
- **Cloud capacity**: Instances may not be available in target regions
- **Timeout**: Test takes longer than expected duration
- **Infrastructure**: Network, authentication, or quota problems
- **Configuration**: Invalid scenario parameters or missing dependencies
