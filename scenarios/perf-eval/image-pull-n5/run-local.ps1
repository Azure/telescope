param(
    [string]$Registry = "williamjcusaue1.azurecr-test.io",
    [string]$Image = "test1gb@sha256:06d20fd1e468005b0fb1b4d3fce678e75f7ec5d9d76e635d335da9d440be25db",
    [string]$Username = "williamjcusaue1",
    [string]$Password = "58jBdanzX98R6zYW4WgoL3T5PZWxMo85RdqUzj43BPriXYrImF81JQQJ99CIADL93NaEqg7NAAACAZCRFR7H",
    [switch]$SetupOnly,
    [switch]$TwoBatches,
    [switch]$Direct,
    [ValidateSet(4, 5)]
    [int]$PullCount = 5
)

$ErrorActionPreference = "Stop"
if ($TwoBatches -and $PullCount -ne 5) {
    throw "Two-batch mode requires five downloads per batch."
}
if ($Direct -and $TwoBatches) {
    throw "Direct mode supports one batch per run."
}
$arguments = @(
    "--registry", $Registry,
    "--image", $Image,
    "--username", $Username,
    "--start-immediately",
    "--pull-count", "$PullCount"
)
if ($SetupOnly) {
    $arguments += "--setup-only"
}
if ($TwoBatches) {
    $arguments += "--two-batches"
}
if ($Direct) {
    $arguments += "--direct"
}

if (-not $SetupOnly -and $Password -and $Password -ne "<REGISTRY_PASSWORD>") {
    $arguments += "--password-stdin"
    $Password | & wsl.exe --distribution Ubuntu --cd $PSScriptRoot --exec python3 -B local.py @arguments
} else {
    & wsl.exe --distribution Ubuntu --cd $PSScriptRoot --exec python3 -B local.py @arguments
}
if ($LASTEXITCODE -ne 0) {
    throw "Local download command failed (exit $LASTEXITCODE). See the diagnostics above."
}
