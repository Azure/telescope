<#
.SYNOPSIS
Telescope Azure Terraform Deployment Script (PowerShell Version)

This script automates Terraform workflows for Azure resources:
- Prerequisites check
- Azure login
- Terraform init, plan, apply, destroy
- Resource group management
#>

#----------------------------------------
# Color Codes for Output
#----------------------------------------
$Host.UI.RawUI.ForegroundColor = "White"
function Write-Info($msg)    { Write-Host "[INFO]    $msg" -ForegroundColor Cyan }
function Write-Success($msg) { Write-Host "[✓]       $msg" -ForegroundColor Green }
function Write-WarningMsg($msg){ Write-Host "[⚠]       $msg" -ForegroundColor Yellow }
function Write-ErrorMsg($msg){ Write-Host "[✗]       $msg" -ForegroundColor Red }
function Write-Header($msg)  { Write-Host "`n================ $msg ================" -ForegroundColor Magenta }

#----------------------------------------
# Default Configuration
#----------------------------------------
$ScenarioType = $env:SCENARIO_TYPE   ? $env:SCENARIO_TYPE   : "perf-eval"
$ScenarioName = $env:SCENARIO_NAME   ? $env:SCENARIO_NAME   : "nap"
$Owner        = $env:OWNER           ? $env:OWNER           : [System.Environment]::UserName
$Region       = $env:REGION          ? $env:REGION          : "eastus2"
$RunId        = $env:RUN_ID          ? $env:RUN_ID          : [int][double]::Parse((Get-Date -UFormat %s))
$AzureSubscriptionId = $env:AZURE_SUBSCRIPTION_ID ? $env:AZURE_SUBSCRIPTION_ID : "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"
$Cloud        = "azure"
$SkipAuth     = $false
$AutoApprove  = $false

# Paths
$RootDir             = Resolve-Path "$PSScriptRoot\..\..\.."
$TerraformModulesDir = Join-Path (Join-Path (Join-Path $RootDir "modules") "terraform") $Cloud
$TerraformInputFile  = Join-Path (Join-Path (Join-Path (Join-Path (Join-Path $RootDir "scenarios") $ScenarioType) $ScenarioName) "terraform-inputs") "$Cloud-complex.tfvars"

#----------------------------------------
# Help
#----------------------------------------
function Print-Help {
@"
Telescope Azure Terraform Deployment Script

Usage: .\script.ps1 [command] [options]

Commands:
  init                Initialize Terraform
  plan                Create Terraform plan
  apply               Apply Terraform plan
  destroy             Destroy all resources
  full                Full workflow (init -> plan -> apply)
  
Options:
  --scenario NAME           Test scenario name (default: nap)
  --scenario-type TYPE      Scenario type (default: perf-eval)
  --region REGION           Azure region (default: eastus2)
  --run-id ID               Unique run identifier (default: timestamp)
  --owner NAME              Resource owner (default: current user)
  --skip-auth               Skip Azure authentication
  --auto-approve            Auto-approve without confirmation
  --help                    Show this help message
"@
}

#----------------------------------------
# Parse Arguments
#----------------------------------------
param(
    [string]$Command = "full",
    [string[]]$Args
)

for ($i=0; $i -lt $Args.Count; $i++) {
    switch ($Args[$i]) {
        "--scenario"      { $ScenarioName = $Args[$i+1]; $i++ }
        "--scenario-type" { $ScenarioType = $Args[$i+1]; $i++ }
        "--region"        { $Region = $Args[$i+1]; $i++ }
        "--run-id"        { $RunId = $Args[$i+1]; $i++ }
        "--owner"         { $Owner = $Args[$i+1]; $i++ }
        "--skip-auth"     { $SkipAuth = $true }
        "--auto-approve"  { $AutoApprove = $true }
        "--help"          { Print-Help; exit 0 }
        default           { Write-ErrorMsg "Unknown option: $($Args[$i])"; Print-Help; exit 1 }
    }
}

#----------------------------------------
# Check Prerequisites
#----------------------------------------
function Check-Prerequisites {
    Write-Header "PREREQUISITES CHECK"
    $AllOk = $true

    if (Get-Command terraform -ErrorAction SilentlyContinue) {
        $tfVersion = terraform version -json | ConvertFrom-Json
        Write-Success "Terraform: $($tfVersion.terraform_version)"
    } else { Write-ErrorMsg "Terraform not found"; $AllOk = $false }

    if (Get-Command az -ErrorAction SilentlyContinue) {
        $azVersion = az version --output json | ConvertFrom-Json
        Write-Success "Azure CLI: $($azVersion.'azure-cli')"
    } else { Write-ErrorMsg "Azure CLI not found"; $AllOk = $false }

    if (Get-Command jq -ErrorAction SilentlyContinue) {
        $jqVersion = jq --version
        Write-Success "jq: $jqVersion"
    } else { Write-ErrorMsg "jq not found"; $AllOk = $false }

    if (-not $AllOk) { Write-ErrorMsg "Install missing prerequisites"; exit 1 }

    Write-Success "All prerequisites satisfied"
}

#----------------------------------------
# Define Variables
#----------------------------------------
function Define-Variables {
    Write-Header "DEFINING VARIABLES"
    $Global:TerraformModulesDir = $TerraformModulesDir
    $Global:TerraformInputFile  = $TerraformInputFile
    $Global:RunId = $RunId
    Write-Info "Scenario: $ScenarioType/$ScenarioName"
    Write-Info "Owner: $Owner"
    Write-Info "Run ID: $RunId"
    Write-Info "Region: $Region"
    Write-Info "Subscription: $AzureSubscriptionId"
    Write-Info "Terraform Dir: $TerraformModulesDir"
    Write-Info "Input File: $TerraformInputFile"
    Write-Success "Variables defined"
}

#----------------------------------------
# Azure Login
#----------------------------------------
function Azure-Login {
    if ($SkipAuth) { Write-WarningMsg "Skipping Azure authentication"; return }

    Write-Header "AZURE AUTHENTICATION"
    if (az account show -ErrorAction SilentlyContinue) {
        Write-Success "Already authenticated"
        $currentSub = az account show --query name -o tsv
        Write-Info "Current subscription: $currentSub"
    } else {
        Write-Info "Logging in..."
        az login --use-device-code
    }
    az account set -s $AzureSubscriptionId
    $Global:ARM_SUBSCRIPTION_ID = az account show --query id -o tsv
    $Global:ARM_TENANT_ID       = az account show --query tenantId -o tsv
    Write-Success "Azure authentication successful"
}

#----------------------------------------
# Create Resource Group
#----------------------------------------
function Create-ResourceGroup {
    if ($SkipAuth) { Write-WarningMsg "Skipping resource group creation"; return }

    Write-Header "CREATE RESOURCE GROUP"
    Write-Info "Creating resource group: $RunId"

    $creationDate = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $deletionTime = (Get-Date).AddHours(2).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

    az group create `
        --name $RunId `
        --location $Region `
        --tags @{ run_id=$RunId; scenario="$ScenarioType-$ScenarioName"; owner=$Owner; creation_date=$creationDate; deletion_due_time=$deletionTime }

    Write-Success "Resource group created: $RunId"
}

#----------------------------------------
# Prepare Terraform Input
#----------------------------------------
function Prepare-TerraformInput {
    Write-Header "PREPARING TERRAFORM INPUT"

    if (-not (Test-Path $TerraformInputFile)) {
        Write-ErrorMsg "Terraform input file not found: $TerraformInputFile"; exit 1
    }

    $Global:InputJson = @{
        run_id = $RunId
        region = $Region
        owner  = $Owner
    } | ConvertTo-Json -Compress

    Write-Info "Terraform input file validated"
    Write-Info "JSON Input: $InputJson"
}

#----------------------------------------
# Terraform Commands
#----------------------------------------
function Terraform-Init {
    Write-Header "TERRAFORM INITIALIZATION"
    Set-Location $TerraformModulesDir
    terraform init -upgrade
    Write-Success "Terraform initialized"
}

function Terraform-Plan {
    Write-Header "TERRAFORM PLAN"
    Set-Location $TerraformModulesDir
    terraform plan -var "json_input=$InputJson" -var-file $TerraformInputFile -out tfplan
    Write-Success "Terraform plan created"
}

function Terraform-Apply {
    Write-Header "TERRAFORM APPLY"
    Set-Location $TerraformModulesDir
    if (-not (Test-Path "tfplan")) { Write-ErrorMsg "Plan file not found. Run 'plan' first."; exit 1 }
    if (-not $AutoApprove) {
        $confirm = Read-Host "Continue with applying resources? (yes/no)"
        if ($confirm -ne "yes") { Write-Info "Apply cancelled"; return }
    }
    terraform apply -auto-approve tfplan
    Write-Success "Infrastructure provisioned successfully"
}

function Terraform-Destroy {
    Write-Header "TERRAFORM DESTROY"
    Set-Location $TerraformModulesDir
    if (-not $AutoApprove) {
        $confirm = Read-Host "Type 'destroy' to confirm destruction of all resources"
        if ($confirm -ne "destroy") { Write-Info "Destroy cancelled"; return }
    }
    terraform destroy -var "json_input=$InputJson" -var-file $TerraformInputFile -auto-approve
    Write-Success "Infrastructure destroyed"
}

function Cleanup-ResourceGroup {
    if ($SkipAuth) { Write-WarningMsg "Skipping resource group deletion"; return }
    Write-Header "FINAL CLEANUP"
    if (-not $AutoApprove) {
        $confirm = Read-Host "Delete Azure resource group '$RunId'? (yes/no)"
        if ($confirm -ne "yes") { Write-Info "Cleanup cancelled"; return }
    }
    az group delete --name $RunId -y
    Write-Success "Resource group deleted"
}

#----------------------------------------
# Main Workflow
#----------------------------------------
Check-Prerequisites
Define-Variables

switch ($Command) {
    "init"    { Terraform-Init }
    "plan"    { Terraform-Init; Prepare-TerraformInput; Terraform-Plan }
    "apply"   { Terraform-Apply }
    "destroy" { Terraform-Destroy; Cleanup-ResourceGroup }
    "full"    { Azure-Login; Create-ResourceGroup; Terraform-Init; Prepare-TerraformInput; Terraform-Plan; Terraform-Apply }
    default   { Write-ErrorMsg "Unknown command: $Command"; Print-Help; exit 1 }
}

Write-Header "✓ WORKFLOW COMPLETE"
