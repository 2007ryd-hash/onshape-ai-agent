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

$script:ExpectedAgentFiles = @(
    'onshape-engineering-cad-agent.md',
    'onshape-engineering-drawing-agent.md',
    'onshape-engineering-engineering-agent.md',
    'onshape-engineering-visual-qa-agent.md'
)

function Get-AbsolutePath([string]$path) {
    return [IO.Path]::GetFullPath($path)
}

function Get-CanonicalDirectoryPath([string]$path) {
    $absolutePath = Get-AbsolutePath $path
    if (Test-Path -LiteralPath $absolutePath -PathType Container) {
        try { return (Resolve-Path -LiteralPath $absolutePath).Path } catch { return $absolutePath }
    }
    return $absolutePath
}

function Read-Marker([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    try { return Get-Content -Raw -LiteralPath $path | ConvertFrom-Json } catch { return $null }
}

function Assert-OwnedMarker([string]$path, [string]$label) {
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    $marker = Read-Marker $path
    if (($null -eq $marker) -or ([string]$marker.repo_root -ne $repoRoot)) {
        throw "$label marker is not owned by this project: $path"
    }
    return $true
}

function Add-UninstallTarget([string]$path, [string]$kind) {
    $absolutePath = Get-AbsolutePath $path
    if (@($script:UninstallTargets | Where-Object { $_.Path -eq $absolutePath }).Count -eq 0) {
        $script:UninstallTargets += [pscustomobject]@{
            Path = $absolutePath
            Kind = $kind
        }
    }
}

function Add-OwnedSkillTargets([string]$destination, [string]$label) {
    $absoluteDestination = Get-AbsolutePath $destination
    $markerPath = "$absoluteDestination.onshape-agent-owner.json"
    $destinationExists = Test-Path -LiteralPath $absoluteDestination
    $markerExists = Test-Path -LiteralPath $markerPath
    if ($markerExists) {
        $null = Assert-OwnedMarker $markerPath $label
        if ($destinationExists) { Add-UninstallTarget $absoluteDestination 'host' }
        Add-UninstallTarget $markerPath 'marker'
    } elseif ($destinationExists) {
        throw "$label destination is not owned by this project: $absoluteDestination"
    }
}

function Remove-InstalledPath([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.LinkType) { Remove-Item -LiteralPath $path -Force } else { Remove-Item -LiteralPath $path -Recurse -Force }
}

function Stage-UninstallTarget([object]$target, [string]$stagingRoot) {
    if (-not (Test-Path -LiteralPath $target.Path)) { return }
    $script:StageCount++
    $requestedFailure = [string]$env:ONSHAPE_AGENT_TEST_UNINSTALL_STAGE
    $numericFailure = 0
    if ([int]::TryParse($requestedFailure, [ref]$numericFailure) -and ($numericFailure -eq $script:StageCount)) {
        throw "Injected uninstall staging failure at target $($script:StageCount)"
    }
    if (($requestedFailure -eq 'state') -and ($target.Kind -eq 'state')) {
        throw 'Injected uninstall staging failure at state target'
    }
    $backupPath = Join-Path $stagingRoot ('item-{0:D4}' -f $script:StageCount)
    Move-Item -LiteralPath $target.Path -Destination $backupPath -Force | Out-Null
    $script:StagedTargets += [pscustomobject]@{
        OriginalPath = $target.Path
        BackupPath = $backupPath
        Kind = $target.Kind
    }
}

function Restore-StagedTargets([string]$stagingRoot) {
    $rollbackErrors = @()
    for ($index = $script:StagedTargets.Count - 1; $index -ge 0; $index--) {
        $entry = $script:StagedTargets[$index]
        try {
            if (($env:ONSHAPE_AGENT_TEST_UNINSTALL_ROLLBACK -eq '1') -and ($index -eq 0)) {
                throw 'Injected uninstall rollback failure'
            }
            if (-not (Test-Path -LiteralPath $entry.BackupPath)) {
                throw "staged backup is missing: $($entry.BackupPath)"
            }
            if (Test-Path -LiteralPath $entry.OriginalPath) { Remove-InstalledPath $entry.OriginalPath }
            Move-Item -LiteralPath $entry.BackupPath -Destination $entry.OriginalPath -Force | Out-Null
        } catch {
            $rollbackErrors += $_.Exception.Message
        }
    }
    if (($rollbackErrors.Count -eq 0) -and (Test-Path -LiteralPath $stagingRoot)) {
        try { Remove-Item -LiteralPath $stagingRoot -Recurse -Force } catch { $rollbackErrors += $_.Exception.Message }
    }
    $script:StagedTargets = @()
    if ($rollbackErrors.Count -gt 0) {
        throw ("Uninstall rollback failed; recoverable backups retained at ${stagingRoot}: " + ($rollbackErrors -join '; '))
    }
}

$script:UninstallTargets = @()
$script:StagedTargets = @()
$script:StageCount = 0

if ($HostTarget -in @('codex', 'all')) {
    Add-OwnedSkillTargets (Join-Path $CodexHome 'skills\onshape-engineering') 'Codex skill'
}
if ($HostTarget -in @('claude', 'all')) {
    Add-OwnedSkillTargets (Join-Path $ClaudeConfigDir 'skills\onshape-engineering') 'Claude skill'
    $agentRoot = Get-CanonicalDirectoryPath (Join-Path $ClaudeConfigDir 'agents')
    $agentMarkerPath = Join-Path $agentRoot '.onshape-engineering-agent-owner.json'
    if (Test-Path -LiteralPath $agentMarkerPath) {
        $null = Assert-OwnedMarker $agentMarkerPath 'Claude agents'
        foreach ($fileName in $script:ExpectedAgentFiles) {
            $agentPath = Join-Path $agentRoot $fileName
            if (Test-Path -LiteralPath $agentPath -PathType Leaf) { Add-UninstallTarget $agentPath 'agent' }
        }
        Add-UninstallTarget $agentMarkerPath 'marker'
    }
}
if ($RemoveRuntime) {
    $runtimePath = Get-AbsolutePath (Join-Path $repoRoot '.venv')
    if (Test-Path -LiteralPath $runtimePath) { Add-UninstallTarget $runtimePath 'runtime' }
}

$statePath = Get-AbsolutePath (Join-Path $StateDir 'install.json')
$state = Read-Marker $statePath
if (($null -ne $state) -and ([string]$state.repo_root -eq $repoRoot)) {
    Add-UninstallTarget $statePath 'state'
}

$removed = @()
$cleanupWarnings = @()
$stagingRoot = $null
try {
    if ($script:UninstallTargets.Count -gt 0) {
        $stagingRoot = Get-AbsolutePath (Join-Path $StateDir ('.onshape-agent-uninstall-' + [Guid]::NewGuid().ToString('N')))
        New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null
        foreach ($target in @($script:UninstallTargets)) {
            Stage-UninstallTarget $target $stagingRoot
        }
        $removed = @($script:StagedTargets | ForEach-Object { $_.OriginalPath })
        if ($env:ONSHAPE_AGENT_TEST_UNINSTALL_CLEANUP -eq '1') {
            $cleanupWarnings += "Unable to remove uninstall backup ${stagingRoot}: Injected cleanup failure"
        } else {
            try {
                Remove-Item -LiteralPath $stagingRoot -Recurse -Force
            } catch {
                $cleanupWarnings += "Unable to remove uninstall backup ${stagingRoot}: $($_.Exception.Message)"
            }
        }
    }
} catch {
    $failure = $_
    if ($null -ne $stagingRoot) {
        try {
            Restore-StagedTargets $stagingRoot
        } catch {
            $rollbackFailure = $_
            throw "Onshape uninstall failed: $($failure.Exception.Message); rollback failed: $($rollbackFailure.Exception.Message)"
        }
    }
    throw $failure
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
    cleanup_warnings = @($cleanupWarnings)
    message = 'Upstream onshape-mcp config and tokens are preserved by default.'
} | ConvertTo-Json -Depth 4 -Compress
