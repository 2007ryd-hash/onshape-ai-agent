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
$script:OnshapeMcpVersion = '0.5.2'
$script:OnshapeMcpPackage = 'onshape-mcp@0.5.2'
$script:OnshapeMcpCommand = @('npx.cmd', '--yes', $script:OnshapeMcpPackage)
$script:OnshapeCallback = 'http://localhost:18338/callback'
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

function Get-NodeCommand() {
    $command = @(Get-Command 'node' -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1
    if ($null -eq $command) { $command = @(Get-Command 'node.exe' -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1 }
    return $command
}

function Assert-NodeAndNpx() {
    $node = Get-NodeCommand
    if ($null -eq $node) { throw 'Node.js 22 or newer is required to use onshape-mcp (node.exe was not found)' }
    try {
        $versionOutput = @(& $node.Source '--version' 2>$null)
        $versionExitCode = $LASTEXITCODE
    } catch {
        throw 'Node.js 22 or newer is required to use onshape-mcp (node --version failed)'
    }
    $versionText = (($versionOutput | Select-Object -First 1) -as [string]).Trim()
    $versionMatch = [regex]::Match($versionText, '^v?(?<major>\d+)(?:\.\d+){0,2}$')
    if (($versionExitCode -ne 0) -or (-not $versionMatch.Success) -or ([int]$versionMatch.Groups['major'].Value -lt 22)) {
        throw 'Node.js 22 or newer is required to use onshape-mcp'
    }
    $npx = @(Get-Command 'npx.cmd' -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1
    if ($null -eq $npx) { throw 'npx.cmd was not found; install Node.js 22 or newer and retry' }
    return $npx
}

function Test-OnshapeMcpPackage([object]$npx) {
    try {
        $versionOutput = @(& $npx.Source '--yes' $script:OnshapeMcpPackage '--version' 2>$null)
        $versionExitCode = $LASTEXITCODE
    } catch {
        return $false
    }
    if ($versionExitCode -ne 0) { return $false }
    $versionText = ($versionOutput | ForEach-Object { [string]$_ }) -join "`n"
    return [regex]::IsMatch($versionText, '(?m)^\s*v?0\.5\.2\s*$')
}

function Get-OnshapeConfigPath() {
    $appDataRoot = if ($env:APPDATA) { $env:APPDATA } else { Join-Path $HOME 'AppData\Roaming' }
    return Join-Path $appDataRoot 'onshape-mcp\config.toml'
}

function Get-OnshapeTokenPath() {
    $localAppDataRoot = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME 'AppData\Local' }
    return Join-Path $localAppDataRoot 'onshape-mcp\tokens.json'
}

$npxCommand = Assert-NodeAndNpx
$mcpPresent = Test-OnshapeMcpPackage $npxCommand
if (-not $mcpPresent) { throw "Unable to verify pinned $script:OnshapeMcpPackage through npx.cmd" }

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
    $pythonCommand = @(Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1
    if ($null -eq $pythonCommand) { $pythonCommand = @(Get-Command python -CommandType Application -ErrorAction Stop) | Select-Object -First 1 }
    $pythonPath = $pythonCommand.Source
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw "Python runtime was not found: $pythonPath" }

New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
$statePath = Join-Path $StateDir 'install.json'
$state = @{
    schema_version = '1.1'
    repo_root = $repoRoot
    python_path = $pythonPath
    host_target = $HostTarget
    installed_paths = @($installedPaths)
    mcp_command = @($script:OnshapeMcpCommand)
    mcp_package = $script:OnshapeMcpPackage
    mcp_version = $script:OnshapeMcpVersion
    mcp_present = [bool]$mcpPresent
    config_present = [bool](Test-Path -LiteralPath (Get-OnshapeConfigPath) -PathType Leaf)
    tokens_present = [bool](Test-Path -LiteralPath (Get-OnshapeTokenPath) -PathType Leaf)
}
$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding utf8
$nextSteps = @(
    'Run scripts/configure-onshape.ps1 to save your user-owned OAuth settings.',
    'Run scripts/login-onshape.ps1 to explicitly authorize the pinned Onshape MCP.',
    'Run scripts/onshape-agent.ps1 doctor --live --json for an explicit live check.'
)
@{
    status = 'INSTALLED'
    host_target = $HostTarget
    runtime_installed = -not [bool]$SkipRuntimeInstall
    state_file = $statePath
    installed_paths = @($installedPaths)
    mcp_package = $script:OnshapeMcpPackage
    mcp_version = $script:OnshapeMcpVersion
    mcp_present = [bool]$mcpPresent
    next_steps = $nextSteps
} | ConvertTo-Json -Depth 5 -Compress
