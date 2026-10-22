param(
    [string]$Registry,
    [string]$Image,
    [string]$Username,
    [string]$Password,
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
# Reuse the saved target settings while requesting exactly four downloads.
& (Join-Path $PSScriptRoot "run-local.ps1") @PSBoundParameters -PullCount 4
