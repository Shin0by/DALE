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
if ($portablePath -ne ($projectRoot + '\DALE')) { throw 'Unexpected portable destination.' }
foreach ($targetPath in @($distributionPath, $buildPath)) {
    if (-not $targetPath.StartsWith($artifactRoot + [System.IO.Path]::DirectorySeparatorChar)) {
        throw 'Build output must stay inside the project artifacts directory.'
    }
}

Push-Location -LiteralPath $projectRoot
try {
    & $projectPython -m PyInstaller --noconfirm --windowed "--$Mode" --noupx `
        --name DALE --paths src --distpath $distributionPath --workpath $buildPath `
        --specpath $buildPath --collect-binaries shapely tools/desktop_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Windows application build failed.' }
    if ($Mode -eq 'onedir') {
        New-Item -ItemType Directory -Path $portablePath -Force | Out-Null
        # Deploy runtime children without nesting DALE/DALE or touching UserData/projects.
        Get-ChildItem -LiteralPath (Join-Path $distributionPath 'DALE') | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $portablePath -Recurse -Force
        }
        Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\portable-start.txt') -Destination (Join-Path $portablePath 'START-HERE.txt') -Force
        $sourceFiles = @(
            foreach ($directory in @('src\dale', 'docs', 'tools', 'tests', 'project', '.github')) {
                Get-ChildItem -LiteralPath (Join-Path $projectRoot $directory) -File -Recurse | Where-Object { $_.Extension -in @('.py', '.ps1', '.cmd', '.json', '.md', '.txt', '.yml') }
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
