param(
    [string]$Registry = "williamjcusaue1.azurecr-test.io",
    [string]$Image = "test1gb@sha256:06d20fd1e468005b0fb1b4d3fce678e75f7ec5d9d76e635d335da9d440be25db",
    [switch]$SetupOnly,
    [switch]$TwoBatches,
    [switch]$Direct,
    [switch]$WarmTraffic,
    [long]$ScaleInThresholdBytes = 4294967296,
    [long]$ScaleOutThresholdBytes = 5368709120,
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
if ($WarmTraffic) {
    $arguments += @(
        "--warm-traffic",
        "--scale-in-threshold-bytes", "$ScaleInThresholdBytes",
        "--scale-out-threshold-bytes", "$ScaleOutThresholdBytes"
    )
}

& wsl.exe --distribution Ubuntu --cd $PSScriptRoot --exec python3 -B local.py @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Local download command failed (exit $LASTEXITCODE). See the diagnostics above."
}
