param(
    [string]$Registry = "williamjcusaue1.azurecr-test.io",
    [string]$Image = "test1gb@sha256:06d20fd1e468005b0fb1b4d3fce678e75f7ec5d9d76e635d335da9d440be25db",
    [string]$MetadataAccount = "dfauemanaged1",
    [string]$RegistryId = "68bf59c7d4f54807aa3dc39e03ad652d",
    [string]$StorageSubscription,
    [ValidateSet(4, 5)]
    [int]$PullCount = 5,
    [switch]$Direct,
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
if ($Registry -notmatch '^[a-z0-9.-]+$' -or
    $Image -notmatch '^[a-z0-9._/-]+@sha256:[0-9a-f]{64}$' -or
    $MetadataAccount -notmatch '^[a-z0-9]{3,24}$' -or
    $RegistryId -notmatch '^[0-9a-f]{32}$') {
    throw "Use a registry hostname, pinned manifest digest, metadata account, and internal registry ID."
}
$arguments = @(
    "--registry", $Registry, "--image", $Image,
    "--primary-target-stdin", "--start-immediately", "--pull-count", "$PullCount"
)
if ($Direct) { $arguments += "--direct" }
if ($SetupOnly) {
    & wsl.exe --distribution Ubuntu --cd $PSScriptRoot --exec python3 -B local.py @arguments --setup-only
    if ($LASTEXITCODE -ne 0) { throw "Primary worker setup failed (exit $LASTEXITCODE)." }
    return
}

$imageReference = "$Registry/$Image"
$raw = & docker manifest inspect $imageReference
if ($LASTEXITCODE -ne 0) {
    throw "Cannot read the pinned manifest. Authenticate Docker to the registry first."
}
$manifest = $raw | ConvertFrom-Json
$layers = @($manifest.layers)
if ($layers.Count -ne 1 -or $layers[0].digest -notmatch '^sha256:[0-9a-f]{64}$' -or
    $layers[0].size -lt 1073741824) {
    throw "The pinned manifest must contain exactly one layer of at least one GiB."
}
$digest = $layers[0].digest
$encoded = $digest.Substring(7)
$partitionKey = "$encoded&$RegistryId"
$auth = @("--auth-mode", "login", "--only-show-errors")
if ($StorageSubscription) { $auth += @("--subscription", $StorageSubscription) }
foreach ($name in @("AZURE_STORAGE_KEY", "AZURE_STORAGE_CONNECTION_STRING", "AZURE_STORAGE_SAS_TOKEN")) {
    if (Test-Path "Env:$name") {
        throw "Remove the inherited $name override before using login-only primary downloads."
    }
}

$previousCloud = $env:AZURE_CLOUD_NAME
$sas = $null
$bundle = $null
try {
    $env:AZURE_CLOUD_NAME = "AzureCloud"
    $raw = az storage entity query @auth --account-name $MetadataAccount `
        --table-endpoint "https://$MetadataAccount.table.core.windows.net" `
        --table-name BlobLocation --filter "PartitionKey eq '$partitionKey' and PrimaryCopy eq true" `
        --select PartitionKey RowKey PrimaryCopy IsElasticCopy Status StorageAccountName StorageContainerName RegistryLoginUri `
        --query items -o json
    if ($LASTEXITCODE -ne 0) {
        throw "Primary metadata lookup failed. Use a public-Azure login with table-read access and, if needed, -StorageSubscription."
    }
    $locations = @($raw | ConvertFrom-Json)
    if ($locations.Count -ne 1) { throw "Expected exactly one primary BlobLocation row." }
    $location = $locations[0]
    $account = $location.StorageAccountName
    $container = $location.StorageContainerName
    if ($location.PrimaryCopy -ne $true -or $location.IsElasticCopy -eq $true -or
        $location.Status -notin @($null, "", "Active") -or
        $account -notmatch '^[a-z0-9]{3,24}$' -or
        $container -notmatch '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$' -or $container -match '--' -or
        $location.PartitionKey -ne $partitionKey -or $location.RowKey -ne "$account&$container" -or
        ($location.RegistryLoginUri -and $location.RegistryLoginUri -ne $Registry)) {
        throw "Primary row identity, status, or location is invalid. No downloads were started."
    }

    $blobName = "docker/registry/v2/blobs/sha256/$($encoded.Substring(0,2))/$encoded/data"
    $expiry = [DateTime]::UtcNow.AddHours(1).ToString("yyyy-MM-ddTHH:mmZ")
    $sas = az storage blob generate-sas @auth --as-user --account-name $account `
        --container-name $container --name $blobName --permissions r --https-only `
        --expiry $expiry --full-uri -o tsv
    if ($LASTEXITCODE -ne 0 -or -not $sas) {
        throw "Could not obtain a read-only primary SAS. Blob-read and user-delegation permissions are required."
    }
    Write-Host "Verified primary: $account / $container; layer $digest; $PullCount downloads."
    $bundle = @{
        image = $imageReference
        registry_id = $RegistryId
        manifest = $manifest
        location = $location
        url = $sas
    } | ConvertTo-Json -Depth 12 -Compress
} finally {
    $env:AZURE_CLOUD_NAME = $previousCloud
    $sas = $null
}

try {
    $bundle | & wsl.exe --distribution Ubuntu --cd $PSScriptRoot --exec python3 -B local.py @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Primary download command failed (exit $LASTEXITCODE). Inspect partial results before retrying."
    }
} finally {
    $bundle = $null
}
