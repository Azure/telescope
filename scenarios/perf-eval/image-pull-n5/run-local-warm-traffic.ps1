param(
    [string]$Registry,
    [string]$Image,
    [switch]$SetupOnly,
    [long]$ScaleInThresholdBytes = 4294967296,
    [long]$ScaleOutThresholdBytes = 5368709120
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "run-local.ps1") @PSBoundParameters -WarmTraffic
