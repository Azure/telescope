# E2E Testing Guide

## What is E2E Testing?

E2E testing in Telescope runs performance benchmarks across cloud providers (Azure, AWS, GCP) using Azure DevOps pipelines to validate test scenarios. It runs all the key steps of the [Design](design.md) using current branch changes.

## Prerequisites

* [Node.js 20+](https://nodejs.org/en/download/) - Required for MCP Azure DevOps server
* [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) - For authentication and Azure operations
* Access to Azure DevOps organization with `telescope` project
* MCP Azure DevOps server configuration file [here](../.vscode/mcp.json)

## Key Information

- Always use ["New Pipeline Test"](../pipelines/system/new-pipeline-test.yml) for running E2E tests
- Project name: `telescope`

## How to Run E2E Test

### Step 1: Start MCP Azure DevOps Server

Before running E2E tests, you need to start the MCP (Model Context Protocol) Azure DevOps server to enable ADO operations:

1. **Start Server**: The MCP server must be started manually by the user. Run the ADO MCP server and provide the Azure DevOps organization name as input when prompted.

2. **Authentication**: Login to Azure using device code authentication:
   ```bash
   az login --use-device-code
   ```

3. **Verify Connection**: Confirm the server is running and accessible by using `mcp_ado_build_get_definitions` command to list available build definitions and ensure the connection is established. Also get the build definition ID for the "New Pipeline Test".

**Note**: The MCP server cannot be started automatically - it must be manually initiated by the user before running E2E tests. The server provides the interface to interact with Azure DevOps APIs for triggering builds, monitoring status, and retrieving logs.

### Step 2: Trigger the ADO Build

1. **Start Build**: Use `mcp_ado_build_run_build` - Start the test with project name, definition ID, and source branch name
2. **Monitor Status**: Use `mcp_ado_build_get_status` - Check the build status every 15 minutes  
3. **Retrieve Logs**: Use `mcp_ado_build_get_log` - Retrieve error logs if the build fails
4. **Get Specific Logs**: Use `mcp_ado_build_get_log_by_id` - Get logs for a specific build log by log ID if the build fails


## Common Issues
- **Cloud capacity**: Instances may not be available in target regions
- **Timeout**: Test takes longer than expected duration
- **Infrastructure**: Network, authentication, or quota problems
- **Configuration**: Invalid scenario parameters or missing dependencies
