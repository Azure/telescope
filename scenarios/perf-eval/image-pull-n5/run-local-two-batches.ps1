param(
    [string]$Registry,
    [string]$Image,
    [string]$Username,
    [string]$Password,
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
# Inherit the saved target settings unless this invocation supplies overrides.
& (Join-Path $PSScriptRoot "run-local.ps1") @PSBoundParameters -TwoBatches
