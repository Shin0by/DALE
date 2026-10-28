param(
    [ValidateSet('onedir', 'onefile')]
    [string] $Mode = 'onedir'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$artifactRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'artifacts'))
$distributionPath = [System.IO.Path]::GetFullPath((Join-Path $artifactRoot "windows\$Mode"))
$buildPath = [System.IO.Path]::GetFullPath((Join-Path $artifactRoot "pyinstaller\$Mode"))
$portablePath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'DALE'))
$appAssetPath = Join-Path $projectRoot 'src\dale\assets'
$appIconPath = Join-Path $appAssetPath 'favicon.ico'
if ($portablePath -ne ($projectRoot + '\DALE')) { throw 'Unexpected portable destination.' }
foreach ($targetPath in @($distributionPath, $buildPath)) {
    if (-not $targetPath.StartsWith($artifactRoot + [System.IO.Path]::DirectorySeparatorChar)) {
        throw 'Build output must stay inside the project artifacts directory.'
    }
}

Push-Location -LiteralPath $projectRoot
try {
    $buildVersion = & $projectPython tools/bump_revision.py
    if ($LASTEXITCODE -ne 0) { throw 'Build revision update failed.' }
    Write-Output ("Building version " + $buildVersion)
    & $projectPython -m PyInstaller --noconfirm --windowed "--$Mode" --noupx `
        --name DALE --paths src --distpath $distributionPath --workpath $buildPath `
        --icon $appIconPath --add-data "${appAssetPath}:dale/assets" `
        --specpath $buildPath --collect-binaries shapely --collect-all pyvips --collect-all UnityPy `
        --collect-all fmod_toolkit --collect-data archspec `
        --copy-metadata pyvips-binary --hidden-import _cffi_backend tools/desktop_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Windows application build failed.' }
    if ($Mode -eq 'onedir') {
        $bundlePath = [System.IO.Path]::GetFullPath((Join-Path $distributionPath 'DALE'))
        Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\portable-start.txt') -Destination (Join-Path $bundlePath 'START-HERE.txt') -Force
        $sourceFiles = @(
            foreach ($directory in @('src\dale', 'docs', 'tools', 'tests', 'project', '.github', 'skills')) {
                Get-ChildItem -LiteralPath (Join-Path $projectRoot $directory) -File -Recurse | Where-Object { $_.Extension -in @('.py', '.ps1', '.cmd', '.json', '.md', '.txt', '.yml', '.png', '.ico') }
            }
            foreach ($file in @('AGENTS.md', 'README.md', '.gitignore', '.gitattributes', '.githooks\pre-push', 'pyproject.toml', 'requirements-build.lock', 'requirements-dev.lock', 'tools\build_windows.ps1', 'tools\desktop_entry.py', 'project\index.json', 'project\state.json')) {
                Get-Item -LiteralPath (Join-Path $projectRoot $file)
            }
        )
        $fingerprints = [ordered]@{}
        foreach ($file in ($sourceFiles | Sort-Object FullName -Unique)) {
            $relative = $file.FullName.Substring($projectRoot.Length + 1).Replace('\', '/')
            $fingerprints[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $runtimeFingerprints = [ordered]@{}
        Get-ChildItem -LiteralPath $bundlePath -File -Recurse | Sort-Object FullName | ForEach-Object {
            $relative = $_.FullName.Substring($bundlePath.Length + 1).Replace([char]92, [char]47)
            $runtimeFingerprints[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $runtimeFingerprints['START-HERE.txt'] = (Get-FileHash -LiteralPath (Join-Path $bundlePath 'START-HERE.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
        $buildInfo = [ordered]@{
            format = 'dale-portable-build'
            version = $buildVersion
            built_utc = [DateTime]::UtcNow.ToString('o')
            mode = $Mode
            source_sha256 = $fingerprints
            runtime_sha256 = $runtimeFingerprints
        }
        $buildInfo | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $bundlePath 'build-info.json') -Encoding UTF8
        & (Join-Path $PSScriptRoot 'publish_windows.ps1') -BundlePath $bundlePath
    }
    else {
        Write-Output (Join-Path $distributionPath 'DALE.exe')
    }
}
finally {
    Pop-Location
}
