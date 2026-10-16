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
        --specpath $buildPath --collect-binaries shapely tools/desktop_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Windows application build failed.' }
    if ($Mode -eq 'onedir') {
        New-Item -ItemType Directory -Path $portablePath -Force | Out-Null
        # Avoid rewriting identical loaded DLLs and preserve a running editor's process.
        $bundlePath = [System.IO.Path]::GetFullPath((Join-Path $distributionPath 'DALE'))
        Get-ChildItem -LiteralPath $bundlePath -File -Recurse | ForEach-Object {
            $sourceFile = $_.FullName
            $relativePath = $sourceFile.Substring($bundlePath.Length + 1)
            $destinationFile = [System.IO.Path]::GetFullPath((Join-Path $portablePath $relativePath))
            if (-not $destinationFile.StartsWith($portablePath + '\')) { throw 'Invalid runtime destination.' }
            $unchanged = (Test-Path -LiteralPath $destinationFile -PathType Leaf) -and (
                (Get-FileHash -LiteralPath $sourceFile).Hash -eq (Get-FileHash -LiteralPath $destinationFile).Hash
            )
            if (-not $unchanged) {
                New-Item -ItemType Directory -Path (Split-Path -Parent $destinationFile) -Force | Out-Null
                try {
                    Copy-Item -LiteralPath $sourceFile -Destination $destinationFile -Force
                }
                catch {
                    if ($relativePath -ne 'DALE.exe') { throw }
                    $previousDirectory = [System.IO.Path]::GetFullPath((Join-Path $artifactRoot ('previous-runtime\' + [guid]::NewGuid().ToString('N'))))
                    if (-not $previousDirectory.StartsWith($artifactRoot + '\')) { throw 'Invalid previous runtime destination.' }
                    New-Item -ItemType Directory -Path $previousDirectory -Force | Out-Null
                    $previousExecutable = Join-Path $previousDirectory 'DALE.exe'
                    Move-Item -LiteralPath $destinationFile -Destination $previousExecutable
                    try {
                        Copy-Item -LiteralPath $sourceFile -Destination $destinationFile
                    }
                    catch {
                        if (Test-Path -LiteralPath $destinationFile -PathType Leaf) {
                            Remove-Item -LiteralPath $destinationFile
                        }
                        Move-Item -LiteralPath $previousExecutable -Destination $destinationFile
                        throw
                    }
                    Write-Output 'Updated executable; an already running editor keeps its current version until restarted.'
                }
            }
        }
        Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\portable-start.txt') -Destination (Join-Path $portablePath 'START-HERE.txt') -Force
        $sourceFiles = @(
            foreach ($directory in @('src\dale', 'docs', 'tools', 'tests', 'project', '.github')) {
                Get-ChildItem -LiteralPath (Join-Path $projectRoot $directory) -File -Recurse | Where-Object { $_.Extension -in @('.py', '.ps1', '.cmd', '.json', '.md', '.txt', '.yml', '.png', '.ico') }
            }
            foreach ($file in @('AGENTS.md', 'README.md', 'pyproject.toml', 'requirements-build.lock', 'requirements-dev.lock', 'tools\build_windows.ps1', 'tools\desktop_entry.py', 'project\index.json', 'project\state.json')) {
                Get-Item -LiteralPath (Join-Path $projectRoot $file)
            }
        )
        $fingerprints = [ordered]@{}
        foreach ($file in ($sourceFiles | Sort-Object FullName -Unique)) {
            $relative = $file.FullName.Substring($projectRoot.Length + 1).Replace('\', '/')
            $fingerprints[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $buildInfo = [ordered]@{
            format = 'dale-portable-build'
            version = $buildVersion
            built_utc = [DateTime]::UtcNow.ToString('o')
            mode = $Mode
            source_sha256 = $fingerprints
        }
        $buildInfo | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $portablePath 'build-info.json') -Encoding UTF8
        Write-Output (Join-Path $portablePath 'DALE.exe')
    }
    else {
        Write-Output (Join-Path $distributionPath 'DALE.exe')
    }
}
finally {
    Pop-Location
}
