param(
    [string]$Registry = "williamjcusaue1.azurecr-test.io",
    [string]$Image = "test1gb@sha256:bec0623e6590d7fe14c2ccb62a0049bfc0386a0e0fe35969f733077f31e7eea4",
    [string]$Username = "williamjcusaue1",
    [string]$Password = "58jBdanzX98R6zYW4WgoL3T5PZWxMo85RdqUzj43BPriXYrImF81JQQJ99CIADL93NaEqg7NAAACAZCRFR7H",
    [switch]$SetupOnly,
    [switch]$TwoBatches,
    [ValidateSet(4, 5)]
    [int]$PullCount = 5
)

$ErrorActionPreference = "Stop"
if ($TwoBatches -and $PullCount -ne 5) {
    throw "Two-batch mode requires five downloads per batch."
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

if (-not $SetupOnly -and $Password -and $Password -ne "<REGISTRY_PASSWORD>") {
    $arguments += "--password-stdin"
    $Password | & wsl.exe --distribution Ubuntu --cd $PSScriptRoot --exec python3 -B local.py @arguments
} else {
    & wsl.exe --distribution Ubuntu --cd $PSScriptRoot --exec python3 -B local.py @arguments
}
if ($LASTEXITCODE -ne 0) {
    throw "Local download command failed (exit $LASTEXITCODE). See the diagnostics above."
}
