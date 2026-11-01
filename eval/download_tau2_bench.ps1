param(
    [string]$Destination = (Join-Path (Split-Path $PSScriptRoot -Parent) "external\benchmarks\tau2-bench")
)

$ErrorActionPreference = "Stop"

$repository = "https://github.com/sierra-research/tau2-bench.git"
$commit = "da0835f6c67baef58bdda18f2a3b037dfb3a1754"
$temporaryClone = Join-Path $env:TEMP ("tau2-bench-" + [guid]::NewGuid().ToString("N"))

$sparsePaths = @(
    "/LICENSE",
    "/data/tau2/benchmarks/text.json",
    "/data/tau2/benchmarks/banking.json",
    "/data/tau2/task_subsets/airline_50.json",
    "/data/tau2/task_subsets/retail_50.json",
    "/data/tau2/task_subsets/telecom_50.json",
    "/data/tau2/task_subsets/banking_knowledge_97.json",
    "/data/tau2/domains/airline/**",
    "/data/tau2/domains/retail/**",
    "/data/tau2/domains/telecom/**",
    "/data/tau2/domains/banking_knowledge/**",
    "!/data/tau2/domains/airline/audio_difficulty.json",
    "!/data/tau2/domains/airline/tasks_voice.json",
    "!/data/tau2/domains/retail/audio_difficulty.json",
    "!/data/tau2/domains/retail/tasks_voice.json",
    "!/data/tau2/domains/telecom/audio_difficulty.json",
    "!/data/tau2/domains/telecom/tasks_voice.json",
    "!/data/tau2/domains/telecom/tasks_full.json",
    "!/data/tau2/domains/banking_knowledge/tasks_voice.json"
)

try {
    & git clone --filter=blob:none --no-checkout --depth 1 $repository $temporaryClone
    if ($LASTEXITCODE -ne 0) { throw "Could not clone the official tau2-bench repository." }

    & git -C $temporaryClone config core.autocrlf false
    if ($LASTEXITCODE -ne 0) { throw "Could not preserve upstream line endings." }

    & git -C $temporaryClone fetch --depth 1 origin $commit
    if ($LASTEXITCODE -ne 0) { throw "Could not fetch pinned commit $commit." }

    & git -C $temporaryClone checkout --detach $commit
    if ($LASTEXITCODE -ne 0) { throw "Could not check out pinned commit $commit." }

    & git -C $temporaryClone sparse-checkout init --no-cone
    if ($LASTEXITCODE -ne 0) { throw "Could not initialize sparse checkout." }

    & git -C $temporaryClone sparse-checkout set --no-cone @sparsePaths
    if ($LASTEXITCODE -ne 0) { throw "Could not select benchmark data files." }

    $targetData = Join-Path $Destination "data\tau2"
    New-Item -ItemType Directory -Force -Path $targetData | Out-Null
    Copy-Item -Path (Join-Path $temporaryClone "data\tau2\*") `
        -Destination $targetData -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $temporaryClone "LICENSE") `
        -Destination (Join-Path $Destination "LICENSE") -Force

    $downloadedFiles = Get-ChildItem -LiteralPath $targetData -Recurse -File |
        Sort-Object FullName |
        ForEach-Object {
            [PSCustomObject]@{
                path = $_.FullName.Substring($targetData.Length + 1)
                size_bytes = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    $manifest = [PSCustomObject]@{
        repository = "https://github.com/sierra-research/tau2-bench"
        commit = $commit
        license = "MIT"
        downloaded_on = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
        domains = @("retail", "airline", "telecom", "banking_knowledge")
        files = @($downloadedFiles)
    }
    $manifest | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath (Join-Path $Destination "download_manifest.json") -Encoding utf8

    Write-Output "Downloaded pinned official tau2 data to $Destination"
    Write-Output ("Files: {0}; bytes: {1}" -f $downloadedFiles.Count, ($downloadedFiles | Measure-Object -Property size_bytes -Sum).Sum)
}
finally {
    if (Test-Path -LiteralPath $temporaryClone) {
        Remove-Item -LiteralPath $temporaryClone -Recurse -Force
    }
}
