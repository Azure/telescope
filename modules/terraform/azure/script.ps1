################################################################################
# Telescope Azure Terraform Deployment Script (PowerShell)
# 
# This script automates the complete Terraform workflow for Azure resources
# including prerequisites check, authentication, planning, and applying
################################################################################

param(
    [string]$Command = "full",
    [string]$Scenario = "nap",
    [string]$ScenarioType = "perf-eval",
    [string]$Region = "eastus2",
    [string]$RunId = [System.DateTime]::UtcNow.Ticks,
    [string]$Owner = $env:USERNAME,
    [switch]$SkipAuth = $false,
    [switch]$AutoApprove = $false,
    [switch]$Help = $false
)

################################################################################
# Helper Functions
################################################################################

function Write-Header {
    param([string]$Message)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Magenta
    Write-Host $Message -ForegroundColor Magenta
    Write-Host "========================================" -ForegroundColor Magenta
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[⚠] $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "[✗] $Message" -ForegroundColor Red
}

function Show-Help {
    Write-Host 'Telescope Azure Terraform Deployment Script'
    Write-Host ''
    Write-Host 'Usage: .\script.ps1 -Command [command] [options]'
    Write-Host ''
    Write-Host 'Commands:'
    Write-Host '  init                Initialize Terraform'
    Write-Host '  plan                Create Terraform plan'
    Write-Host '  apply               Apply Terraform plan (provisions resources)'
    Write-Host '  destroy             Destroy all resources'
    Write-Host '  full                Full workflow (init -> plan -> apply)'
    Write-Host ''
    Write-Host 'Options:'
    Write-Host '  -Scenario NAME           Test scenario name (default: nap)'
    Write-Host '  -ScenarioType TYPE       Scenario type (default: perf-eval)'
    Write-Host '  -Region REGION          Azure region (default: eastus2)'
    Write-Host '  -RunId ID               Unique run identifier (default: timestamp)'
    Write-Host '  -Owner NAME             Resource owner (default: current user)'
    Write-Host '  -SkipAuth               Skip Azure authentication'
    Write-Host '  -AutoApprove            Auto-approve without confirmation'
    Write-Host '  -Help                   Show this help message'
    Write-Host ''
    Write-Host 'Examples:'
    Write-Host '  .\script.ps1 -Command full                              # Complete workflow'
    Write-Host '  .\script.ps1 -Command plan -Scenario nap               # Plan only'
    Write-Host '  .\script.ps1 -Command apply -AutoApprove               # Apply with auto-approval'
    Write-Host '  .\script.ps1 -Command destroy -AutoApprove             # Destroy resources'
    Write-Host '  .\script.ps1 -Command full -Region westus2             # Full workflow in different region'
    Write-Host ''
    Write-Host 'Prerequisites:'
    Write-Host '  - Terraform version 1.7.3 or higher'
    Write-Host '  - Azure CLI version 2.57.0 or higher'
    Write-Host '  - PowerShell version 5.1 or higher'
}

################################################################################
# Configuration
################################################################################

if ($Help) {
    Show-Help
    exit 0
}

$AzureSubscriptionId = "c0d4b923-b5ea-4f8f-9b56-5390a9bf2248"
$Cloud = "azure"

# Derived paths - handle both regular and WSL PowerShell
if ($PSScriptRoot) {
    $RootDir = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
} else {
    # Fallback for WSL or other environments
    $RootDir = (Get-Location).Path
    while ((Split-Path -Leaf $RootDir) -ne "telescope") {
        $RootDir = Split-Path -Parent $RootDir
        if ($RootDir -eq "" -or $RootDir -eq "/") {
            Write-Error "Could not find telescope root directory. Please run script from within the telescope project."
            exit 1
        }
    }
}

$TerraformModulesDir = Join-Path (Join-Path (Join-Path $RootDir "modules") "terraform") $Cloud
$TerraformInputFile = Join-Path (Join-Path (Join-Path (Join-Path (Join-Path $RootDir "scenarios") $ScenarioType) $Scenario) "terraform-inputs") "${Cloud}-complex.tfvars"

################################################################################
# Step 1: Prerequisites Check
################################################################################

function Check-Prerequisites {
    Write-Header "1. PREREQUISITES CHECK"
    
    $allOk = $true
    
    # Check Terraform
    $terraform = Get-Command terraform -ErrorAction SilentlyContinue
    if ($terraform) {
        try {
            $tfVersion = (terraform version -json | ConvertFrom-Json).terraform_version
            Write-Success "Terraform: $tfVersion"
        } catch {
            Write-Error "Terraform found but version check failed"
            $allOk = $false
        }
    } else {
        Write-Error "Terraform not found"
        $allOk = $false
    }
    
    # Check Azure CLI
    $az = Get-Command az -ErrorAction SilentlyContinue
    if ($az) {
        try {
            $azVersion = (az version --output json | ConvertFrom-Json)."azure-cli"
            Write-Success "Azure CLI: $azVersion"
        } catch {
            Write-Error "Azure CLI found but version check failed"
            $allOk = $false
        }
    } else {
        Write-Error "Azure CLI not found"
        $allOk = $false
    }
    
    # Check jq (optional for Windows, can use PowerShell JSON parsing)
    $jq = Get-Command jq -ErrorAction SilentlyContinue
    if ($jq) {
        Write-Success "jq is available (will use PowerShell JSON parsing instead)"
    } else {
        Write-Warning "jq not found - will use PowerShell JSON parsing"
    }
    
    if (-not $allOk) {
        Write-Error "Please install missing prerequisites"
        exit 1
    }
    
    Write-Success "All prerequisites satisfied"
}

################################################################################
# Step 2: Define Variables
################################################################################

function Define-Variables {
    Write-Header "2. DEFINING VARIABLES"
    
    Write-Info "Configuration Summary:"
    Write-Host "  Scenario: $ScenarioType/$Scenario"
    Write-Host "  Owner: $Owner"
    Write-Host "  Run ID: $RunId"
    Write-Host "  Region: $Region"
    Write-Host "  Subscription: $AzureSubscriptionId"
    Write-Host "  Terraform Dir: $TerraformModulesDir"
    Write-Host "  Input File: $TerraformInputFile"
    
    Write-Success "Variables defined"
}

################################################################################
# Step 3: Azure Authentication
################################################################################

function Azure-Login {
    if ($SkipAuth) {
        Write-Warning "Skipping Azure authentication (SkipAuth switch enabled)"
        return
    }
    
    Write-Header "3. AZURE AUTHENTICATION"
    
    try {
        $currentAccount = az account show | ConvertFrom-Json
        Write-Success "Already authenticated to Azure"
        Write-Info "Current subscription: $($currentAccount.name)"
    } catch {
        Write-Info "Logging into Azure..."
        az login --use-device-code
    }
    
    Write-Info "Setting subscription..."
    az account set -s $AzureSubscriptionId
    
    Write-Success "Azure authentication successful"
}

################################################################################
# Step 4: Create Resource Group
################################################################################

function Create-ResourceGroup {
    if ($SkipAuth) {
        Write-Warning "Skipping resource group creation (SkipAuth switch enabled)"
        return
    }
    
    Write-Header "4. CREATE RESOURCE GROUP"
    
    Write-Info "Creating resource group: $RunId"
    
    $creationDate = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $deletionTime = (Get-Date).AddHours(2).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    
    az group create `
        --name $RunId `
        --location $Region `
        --tags `
            "run_id=$RunId" `
            "scenario=${ScenarioType}-${Scenario}" `
            "owner=$Owner" `
            "creation_date=$creationDate" `
            "deletion_due_time=$deletionTime"
    
    Write-Success "Resource group created: $RunId"
}

################################################################################
# Step 5: Prepare Terraform Input
################################################################################

function Prepare-TerraformInput {
    Write-Header "5. PREPARING TERRAFORM INPUT"
    
    Write-Info "Input File: $TerraformInputFile"
    
    if (-not (Test-Path $TerraformInputFile)) {
        Write-Error "Terraform input file not found: $TerraformInputFile"
        exit 1
    }
    
    # Create INPUT_JSON for Terraform
    Write-Info "Creating JSON input for Terraform..."
    $inputJson = @{
        run_id = $RunId
        region = $Region
        owner  = $Owner
    } | ConvertTo-Json -Compress
    
    Write-Success "Terraform input file validated"
    Write-Info "JSON Input: $inputJson"
    
    return $inputJson
}

################################################################################
# Step 6: Terraform Initialize
################################################################################

function Terraform-Init {
    Write-Header "6. TERRAFORM INITIALIZATION"
    
    Write-Info "Directory: $TerraformModulesDir"
    
    if (-not (Test-Path $TerraformModulesDir)) {
        Write-Error "Terraform modules directory not found: $TerraformModulesDir"
        exit 1
    }
    
    Push-Location $TerraformModulesDir
    
    Write-Info "Running terraform init..."
    terraform init -upgrade
    
    Pop-Location
    
    Write-Success "Terraform initialized"
}

################################################################################
# Step 7: Terraform Plan
################################################################################

function Terraform-Plan {
    param([string]$InputJson)
    
    Write-Header "7. TERRAFORM PLAN"
    
    Push-Location $TerraformModulesDir
    
    # Clean up old plan files from different Terraform versions
    if (Test-Path "tfplan") {
        Remove-Item "tfplan" -Force
        Write-Info "Removed old plan file"
    }
    
    Write-Info "Running terraform plan..."
    Write-Info "Variables:"
    Write-Host "  owner: $Owner"
    Write-Host "  scenario_type: $ScenarioType"
    Write-Host "  scenario_name: $Scenario"
    Write-Host "  region: $Region"
    Write-Host "  json_input: $InputJson"
    
    # Escape the JSON properly for PowerShell and Terraform
    $jsonEscaped = $InputJson -replace '"', '\"'
    
    terraform plan `
        -lock=false `
        -var "json_input=$jsonEscaped" `
        -var-file "$TerraformInputFile" `
        -out=tfplan
    
    Pop-Location
    
    Write-Success "Terraform plan created"
}

################################################################################
# Step 8: Terraform Apply
################################################################################

function Terraform-Apply {
    Write-Header "8. TERRAFORM APPLY"
    
    Push-Location $TerraformModulesDir
    
    if (-not (Test-Path "tfplan")) {
        Write-Error "Plan file not found. Run 'plan' first."
        Pop-Location
        exit 1
    }
    
    Write-Warning "WARNING: This will create actual Azure resources!"
    Write-Warning "NOTE: This may incur costs in your Azure subscription"
    Write-Warning "NOTE: Resources will be tagged for deletion in 2 hours"
    
    if (-not $AutoApprove) {
        Write-Host ""
        $confirm = Read-Host "Continue? (yes/no)"
        if ($confirm -ne "yes") {
            Write-Info "Apply cancelled"
            Pop-Location
            return
        }
    }
    
    Write-Info "Applying Terraform plan..."
    terraform apply -lock=false -auto-approve tfplan
    
    Pop-Location
    
    Write-Success "Infrastructure provisioned successfully"
}

################################################################################
# Step 9: Terraform Destroy
################################################################################

function Terraform-Destroy {
    param([string]$InputJson)
    
    Write-Header "9. TERRAFORM DESTROY"
    
    Push-Location $TerraformModulesDir
    
    Write-Warning "WARNING: This will destroy ALL provisioned resources!"
    Write-Warning "NOTE: Make sure to save any important data before proceeding"
    
    if (-not $AutoApprove) {
        Write-Host ""
        $confirm = Read-Host "Type 'destroy' to confirm"
        if ($confirm -ne "destroy") {
            Write-Info "Destroy cancelled"
            Pop-Location
            return
        }
    }
    
    Write-Info "Destroying infrastructure..."
    $jsonEncoded = $InputJson | ConvertFrom-Json | ConvertTo-Json -Compress
    
    terraform destroy `
        -lock=false `
        -var "json_input=$jsonEncoded" `
        -var-file $TerraformInputFile `
        -auto-approve
    
    Pop-Location
    
    Write-Success "Infrastructure destroyed"
}

################################################################################
# Step 10: Cleanup
################################################################################

function Cleanup-ResourceGroup {
    if ($SkipAuth) {
        Write-Warning "Skipping resource group deletion (SkipAuth switch enabled)"
        return
    }
    
    Write-Header "10. FINAL CLEANUP"
    
    Write-Warning "Deleting resource group: $RunId"
    
    if (-not $AutoApprove) {
        $confirm = Read-Host "Continue? (yes/no)"
        if ($confirm -ne "yes") {
            Write-Info "Cleanup cancelled"
            return
        }
    }
    
    az group delete --name $RunId -y
    Write-Success "Resource group deleted"
}

################################################################################
# Main Workflow
################################################################################

function Main {
    switch ($Command.ToLower()) {
        "init" {
            Check-Prerequisites
            Define-Variables
            Terraform-Init
            break
        }
        "plan" {
            Check-Prerequisites
            Define-Variables
            Terraform-Init
            $inputJson = Prepare-TerraformInput
            Terraform-Plan $inputJson
            break
        }
        "apply" {
            Check-Prerequisites
            Define-Variables
            Terraform-Apply
            break
        }
        "destroy" {
            Check-Prerequisites
            Define-Variables
            $inputJson = Prepare-TerraformInput
            Terraform-Destroy $inputJson
            Cleanup-ResourceGroup
            break
        }
        "full" {
            Check-Prerequisites
            Define-Variables
            Azure-Login
            Create-ResourceGroup
            Terraform-Init
            $inputJson = Prepare-TerraformInput
            Terraform-Plan $inputJson
            Terraform-Apply
            break
        }
        default {
            Write-Error "Unknown command: $Command"
            Show-Help
            exit 1
        }
    }
    
    Write-Header "WORKFLOW COMPLETE"
}

################################################################################
# Execute
################################################################################

Main
