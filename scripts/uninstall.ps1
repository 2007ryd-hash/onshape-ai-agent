[CmdletBinding()]
param(
    [ValidateSet('codex', 'claude', 'all')][string]$HostTarget = 'all',
    [switch]$RemoveRuntime,
    [string]$CodexHome,
    [string]$ClaudeConfigDir,
    [string]$StateDir
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($CodexHome)) { $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' } }
if ([string]::IsNullOrWhiteSpace($ClaudeConfigDir)) { $ClaudeConfigDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' } }
if ([string]::IsNullOrWhiteSpace($StateDir)) { $StateDir = if ($env:ONSHAPE_AGENT_STATE_DIR) { $env:ONSHAPE_AGENT_STATE_DIR } else { Join-Path $env:LOCALAPPDATA 'onshape-engineering-agent' } }

function Read-Marker([string]$path) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    try { return Get-Content -Raw -LiteralPath $path | ConvertFrom-Json } catch { return $null }
}

function Remove-InstalledDirectory([string]$destination) {
    $markerPath = "$destination.onshape-agent-owner.json"
    $marker = Read-Marker $markerPath
    if (($null -eq $marker) -or ($marker.repo_root -ne $repoRoot)) { return $false }
    if (Test-Path -LiteralPath $destination) {
        $item = Get-Item -LiteralPath $destination -Force
        if ($item.LinkType) { Remove-Item -LiteralPath $destination -Force } else { Remove-Item -LiteralPath $destination -Recurse -Force }
    }
    Remove-Item -LiteralPath $markerPath -Force
    return $true
}

$removed = @()
if ($HostTarget -in @('codex', 'all')) {
    $destination = Join-Path $CodexHome 'skills\onshape-engineering'
    if (Remove-InstalledDirectory $destination) { $removed += $destination }
}
if ($HostTarget -in @('claude', 'all')) {
    $destination = Join-Path $ClaudeConfigDir 'skills\onshape-engineering'
    if (Remove-InstalledDirectory $destination) { $removed += $destination }
    $agentRoot = Join-Path $ClaudeConfigDir 'agents'
    $agentMarkerPath = Join-Path $agentRoot '.onshape-engineering-agent-owner.json'
    $agentMarker = Read-Marker $agentMarkerPath
    if (($null -ne $agentMarker) -and ($agentMarker.repo_root -eq $repoRoot)) {
        foreach ($path in $agentMarker.installed_files) {
            if (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force; $removed += $path }
        }
        Remove-Item -LiteralPath $agentMarkerPath -Force
    }
}

$statePath = Join-Path $StateDir 'install.json'
$state = Read-Marker $statePath
if (($null -ne $state) -and ($state.repo_root -eq $repoRoot)) { Remove-Item -LiteralPath $statePath -Force }
if ($RemoveRuntime) {
    $runtime = Join-Path $repoRoot '.venv'
    if (Test-Path -LiteralPath $runtime -PathType Container) { Remove-Item -LiteralPath $runtime -Recurse -Force; $removed += $runtime }
}
$appDataRoot = if ($env:APPDATA) { $env:APPDATA } else { Join-Path $HOME 'AppData\Roaming' }
$localAppDataRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME 'AppData\Local' }
$preservedPaths = @(
    (Join-Path $appDataRoot 'onshape-mcp\config.toml'),
    (Join-Path $localAppDataRoot 'onshape-mcp\tokens.json')
)
@{
    status = 'UNINSTALLED'
    host_target = $HostTarget
    removed_paths = @($removed)
    preserved_paths = $preservedPaths
    message = 'Upstream onshape-mcp config and tokens are preserved by default.'
} | ConvertTo-Json -Depth 4 -Compress
