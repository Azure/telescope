param(
    [string]$Registry,
    [string]$Image,
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
# Reuse the saved target settings while requesting exactly four downloads.
& (Join-Path $PSScriptRoot "run-local.ps1") @PSBoundParameters -PullCount 4
