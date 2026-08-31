[CmdletBinding()]
param(
    [ValidateSet('codex', 'claude', 'all')][string]$HostTarget = 'all',
    [switch]$Force,
    [switch]$SkipRuntimeInstall,
    [string]$CodexHome,
    [string]$ClaudeConfigDir,
    [string]$StateDir
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pluginRoot = Join-Path $repoRoot 'plugins\onshape-engineering-agent'
$skillSource = Join-Path $pluginRoot 'skills\onshape-engineering'
$agentSource = Join-Path $pluginRoot 'agents'

if ([string]::IsNullOrWhiteSpace($CodexHome)) {
    $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
}
if ([string]::IsNullOrWhiteSpace($ClaudeConfigDir)) {
    $ClaudeConfigDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' }
}
if ([string]::IsNullOrWhiteSpace($StateDir)) {
    $StateDir = if ($env:ONSHAPE_AGENT_STATE_DIR) { $env:ONSHAPE_AGENT_STATE_DIR } else { Join-Path $env:LOCALAPPDATA 'onshape-engineering-agent' }
}

function Get-OwnerRepo([string]$markerPath) {
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) { return $null }
    try { return (Get-Content -Raw -LiteralPath $markerPath | ConvertFrom-Json).repo_root } catch { return $null }
}

function Remove-InstalledPath([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.LinkType) { Remove-Item -LiteralPath $path -Force } else { Remove-Item -LiteralPath $path -Recurse -Force }
}

function Install-OwnedDirectory([string]$source, [string]$destination) {
    $parent = Split-Path -Parent $destination
    $marker = "$destination.onshape-agent-owner.json"
    $owner = Get-OwnerRepo $marker
    if (Test-Path -LiteralPath $destination) {
        if (($owner -ne $repoRoot) -and (-not $Force)) { throw "Destination is not owned by this project: $destination" }
        Remove-InstalledPath $destination
    }
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    try { New-Item -ItemType Junction -Path $destination -Target $source -Force | Out-Null } catch { Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force }
    @{ repo_root = $repoRoot; destination = $destination } | ConvertTo-Json -Compress | Set-Content -LiteralPath $marker -Encoding utf8
    return $destination
}

function Install-ClaudeAgents([string]$configRoot) {
    $destinationRoot = Join-Path $configRoot 'agents'
    $marker = Join-Path $destinationRoot '.onshape-engineering-agent-owner.json'
    $owner = Get-OwnerRepo $marker
    $sources = @(Get-ChildItem -LiteralPath $agentSource -Filter '*-agent.md' -File)
    $targets = @($sources | ForEach-Object { Join-Path $destinationRoot "onshape-engineering-$($_.Name)" })
    $occupied = @($targets | Where-Object { Test-Path -LiteralPath $_ })
    if (($occupied.Count -gt 0) -and ($owner -ne $repoRoot) -and (-not $Force)) { throw "Claude agent destination is not owned by this project: $destinationRoot" }
    New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
    for ($index = 0; $index -lt $sources.Count; $index++) { Copy-Item -LiteralPath $sources[$index].FullName -Destination $targets[$index] -Force }
    @{ repo_root = $repoRoot; installed_files = $targets } | ConvertTo-Json -Compress | Set-Content -LiteralPath $marker -Encoding utf8
    return $targets
}

$installedPaths = @()
if ($HostTarget -in @('codex', 'all')) { $installedPaths += Install-OwnedDirectory $skillSource (Join-Path $CodexHome 'skills\onshape-engineering') }
if ($HostTarget -in @('claude', 'all')) {
    $installedPaths += Install-OwnedDirectory $skillSource (Join-Path $ClaudeConfigDir 'skills\onshape-engineering')
    $installedPaths += Install-ClaudeAgents $ClaudeConfigDir
}

$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not $SkipRuntimeInstall) {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        & py -3.12 -m venv (Join-Path $repoRoot '.venv') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python 3.12 virtual environment' }
    }
    & $pythonPath -m pip install -e $repoRoot | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install onshape-engineering-agent runtime' }
} elseif (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    $pythonPath = (Get-Command python.exe -ErrorAction Stop).Source
}

New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
$statePath = Join-Path $StateDir 'install.json'
@{ schema_version = '1.0'; repo_root = $repoRoot; python_path = $pythonPath; host_target = $HostTarget; installed_paths = @($installedPaths) } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding utf8
@{ status = 'INSTALLED'; host_target = $HostTarget; runtime_installed = -not [bool]$SkipRuntimeInstall; state_file = $statePath; installed_paths = @($installedPaths) } | ConvertTo-Json -Depth 4 -Compress
