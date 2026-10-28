param([string] $BundlePath)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$artifactRoot = Join-Path $projectRoot 'artifacts'
$portablePath = Join-Path $projectRoot 'DALE'
if (-not $BundlePath) { $BundlePath = Join-Path $artifactRoot 'windows\onedir\DALE' }
$BundlePath = [System.IO.Path]::GetFullPath($BundlePath)
if (-not $BundlePath.StartsWith($artifactRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The staged bundle must be inside the project artifacts directory.'
}
$metadata = Get-Content -LiteralPath (Join-Path $BundlePath 'build-info.json') -Raw | ConvertFrom-Json
$files = @($metadata.runtime_sha256.PSObject.Properties.Name) + @('build-info.json')
foreach ($relative in $files) {
    if ($relative -notin @('DALE.exe', 'START-HERE.txt', 'build-info.json') -and
        -not $relative.StartsWith('_internal/')) { throw 'Unexpected portable runtime member.' }
    $source = [System.IO.Path]::GetFullPath((Join-Path $BundlePath $relative))
    $target = [System.IO.Path]::GetFullPath((Join-Path $portablePath $relative))
    if (-not $source.StartsWith($BundlePath + '\') -or -not $target.StartsWith($portablePath + '\')) {
        throw 'Invalid bundle destination.'
    }
    if ($relative -ne 'build-info.json' -and
        (Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant() -ne $metadata.runtime_sha256.$relative) {
        throw "Staged runtime checksum mismatch: $relative"
    }
}
New-Item -ItemType Directory -Path $portablePath -Force | Out-Null
$executable = Join-Path $portablePath 'DALE.exe'
$guard = $null
try {
    # An executing image cannot be opened for writing. Keep the exclusive handle
    # until publication ends, also preventing a new launch during the update.
    try {
        $guard = [System.IO.File]::Open($executable, [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    }
    catch {
        throw "Portable publication deferred: close DALE after saving, then run tools/publish_windows.ps1. The complete build is ready at $BundlePath. The running application was not changed."
    }
    # Write the executable last. Never rename a running executable: its lazy PYZ
    # importer reopens the original filename and would read incompatible offsets.
    foreach ($relative in $files | Where-Object { $_ -ne 'DALE.exe' }) {
        $source = Join-Path $BundlePath $relative
        $target = Join-Path $portablePath $relative
        if ((Test-Path -LiteralPath $target -PathType Leaf) -and
            (Get-FileHash -LiteralPath $source).Hash -eq (Get-FileHash -LiteralPath $target).Hash) {
            continue
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
    $backup = [System.IO.MemoryStream]::new()
    $guard.Position = 0
    $guard.CopyTo($backup)
    try {
        $inputFile = [System.IO.File]::OpenRead((Join-Path $BundlePath 'DALE.exe'))
        try {
            $guard.Position = 0
            $guard.SetLength(0)
            $inputFile.CopyTo($guard)
            $guard.Flush($true)
        }
        finally { $inputFile.Dispose() }
    }
    catch {
        $guard.Position = 0
        $guard.SetLength(0)
        $backup.Position = 0
        $backup.CopyTo($guard)
        $guard.Flush($true)
        throw
    }
    finally { $backup.Dispose() }
}
finally {
    if ($null -ne $guard) { $guard.Dispose() }
}
Write-Output $executable
