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

function Write-JsonAtomic([string]$path, [object]$value) {
    $parent = Split-Path -Parent $path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $json = $value | ConvertTo-Json -Depth 10
    $fileId = [Guid]::NewGuid().ToString('N')
    $temporaryPath = "$path.$fileId.tmp"
    $backupPath = "$path.$fileId.bak"
    try {
        [IO.File]::WriteAllText($temporaryPath, $json, (New-Object Text.UTF8Encoding($false)))
        if ([IO.File]::Exists($path)) {
            [IO.File]::Replace($temporaryPath, $path, $backupPath, $true)
        } else {
            [IO.File]::Move($temporaryPath, $path)
        }
    } finally {
        if ([IO.File]::Exists($temporaryPath)) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
        if ([IO.File]::Exists($backupPath)) {
            Remove-Item -LiteralPath $backupPath -Force -ErrorAction SilentlyContinue
        }
    }
}

$script:TransactionId = [Guid]::NewGuid().ToString('N')
$script:TransactionEntries = @()
$script:TransactionCreated = @()

function Add-TransactionBackup([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return }
    if (@($script:TransactionEntries | Where-Object { $_.Path -eq $path }).Count -gt 0) { return }
    $backupPath = "$path.onshape-agent-backup-$script:TransactionId"
    Move-Item -LiteralPath $path -Destination $backupPath -Force | Out-Null
    $script:TransactionEntries += [pscustomobject]@{
        Path = $path
        BackupPath = $backupPath
    }
}

function Add-TransactionCreated([string]$path) {
    if ($script:TransactionCreated -notcontains $path) { $script:TransactionCreated += $path }
}

function Remove-TransactionPath([string]$path) {
    if (Test-Path -LiteralPath $path) { Remove-InstalledPath $path }
}

function Invoke-TransactionRollback() {
    for ($index = $script:TransactionCreated.Count - 1; $index -ge 0; $index--) {
        Remove-TransactionPath $script:TransactionCreated[$index]
    }
    for ($index = $script:TransactionEntries.Count - 1; $index -ge 0; $index--) {
        $entry = $script:TransactionEntries[$index]
        if (Test-Path -LiteralPath $entry.BackupPath) {
            if (Test-Path -LiteralPath $entry.Path) { Remove-InstalledPath $entry.Path }
            Move-Item -LiteralPath $entry.BackupPath -Destination $entry.Path -Force | Out-Null
        }
    }
}

function Invoke-TransactionCommit() {
    foreach ($entry in @($script:TransactionEntries)) {
        if (Test-Path -LiteralPath $entry.BackupPath) { Remove-InstalledPath $entry.BackupPath }
    }
    $script:TransactionEntries = @()
    $script:TransactionCreated = @()
}

function Assert-DirectoryTarget([string]$path) {
    if (Test-Path -LiteralPath $path -PathType Leaf) { throw "Destination is a file: $path" }
    $parent = Split-Path -Parent $path
    if (Test-Path -LiteralPath $parent -PathType Leaf) { throw "Destination parent is a file: $parent" }
}

function Test-PythonImport([string]$pythonPath, [string]$sourceRoot) {
    $previousPythonPath = $env:PYTHONPATH
    try {
        if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
            $env:PYTHONPATH = $sourceRoot
        } else {
            $env:PYTHONPATH = "$sourceRoot$([IO.Path]::PathSeparator)$previousPythonPath"
        }
        & $pythonPath -c 'import onshape_agent' 1>$null 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        if ($null -eq $previousPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONPATH = $previousPythonPath
        }
    }
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
    Add-TransactionCreated $destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    try { New-Item -ItemType Junction -Path $destination -Target $source -Force | Out-Null } catch { Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force }
    Add-TransactionCreated $marker
    Write-JsonAtomic $marker @{ repo_root = $repoRoot; destination = $destination }
    return $destination
}

function Install-ClaudeAgents([string]$configRoot) {
    $destinationRoot = Join-Path $configRoot 'agents'
    $marker = Join-Path $destinationRoot '.onshape-engineering-agent-owner.json'
    $sources = @(Get-ChildItem -LiteralPath $agentSource -Filter '*-agent.md' -File)
    $targets = @($sources | ForEach-Object { Join-Path $destinationRoot "onshape-engineering-$($_.Name)" })
    New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
    for ($index = 0; $index -lt $sources.Count; $index++) {
        Add-TransactionCreated $targets[$index]
        Copy-Item -LiteralPath $sources[$index].FullName -Destination $targets[$index] -Force
    }
    Add-TransactionCreated $marker
    Write-JsonAtomic $marker @{ repo_root = $repoRoot; installed_files = $targets }
    return $targets
}

$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not $SkipRuntimeInstall) {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        $pyCommand = @(Get-Command 'py.exe' -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1
        if ($null -eq $pyCommand) { $pyCommand = @(Get-Command 'py' -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1 }
        if ($null -eq $pyCommand) { throw 'Python launcher py.exe was not found; install Python 3.12 and retry' }
        & $pyCommand.Source '-3.12' '-m' 'venv' (Join-Path $repoRoot '.venv') 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python 3.12 virtual environment' }
    }
    & $pythonPath -m pip install -e $repoRoot 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install onshape-engineering-agent runtime' }
} elseif (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    $pythonCommand = @(Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1
    if ($null -eq $pythonCommand) { $pythonCommand = @(Get-Command python -CommandType Application -ErrorAction Stop) | Select-Object -First 1 }
    $pythonPath = $pythonCommand.Source
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw "Python runtime was not found: $pythonPath" }

$sourceRoot = Join-Path $repoRoot 'src'
if (-not (Test-PythonImport $pythonPath $sourceRoot)) {
    throw 'Selected Python runtime cannot import onshape_agent with the repository source path'
}

$codexDestination = Join-Path $CodexHome 'skills\onshape-engineering'
$claudeDestination = Join-Path $ClaudeConfigDir 'skills\onshape-engineering'
$claudeAgentRoot = Join-Path $ClaudeConfigDir 'agents'
$claudeAgentMarker = Join-Path $claudeAgentRoot '.onshape-engineering-agent-owner.json'
$claudeSources = @(Get-ChildItem -LiteralPath $agentSource -Filter '*-agent.md' -File)
if (-not (Test-Path -LiteralPath $skillSource -PathType Container)) { throw "Skill source is missing: $skillSource" }
if (-not (Test-Path -LiteralPath $agentSource -PathType Container)) { throw "Agent source is missing: $agentSource" }
$claudeTargets = @($claudeSources | ForEach-Object { Join-Path $claudeAgentRoot "onshape-engineering-$($_.Name)" })

$pathsToBackup = @()
if ($HostTarget -in @('codex', 'all')) {
    Assert-DirectoryTarget $codexDestination
    $codexMarker = "$codexDestination.onshape-agent-owner.json"
    $codexOwner = Get-OwnerRepo $codexMarker
    if ((Test-Path -LiteralPath $codexDestination) -and ($codexOwner -ne $repoRoot) -and (-not $Force)) {
        throw "Destination is not owned by this project: $codexDestination"
    }
    $pathsToBackup += $codexDestination
    $pathsToBackup += $codexMarker
}
if ($HostTarget -in @('claude', 'all')) {
    Assert-DirectoryTarget $claudeDestination
    Assert-DirectoryTarget $ClaudeConfigDir
    Assert-DirectoryTarget $claudeAgentRoot
    $claudeMarker = "$claudeDestination.onshape-agent-owner.json"
    $claudeOwner = Get-OwnerRepo $claudeMarker
    if ((Test-Path -LiteralPath $claudeDestination) -and ($claudeOwner -ne $repoRoot) -and (-not $Force)) {
        throw "Destination is not owned by this project: $claudeDestination"
    }
    $agentOwner = Get-OwnerRepo $claudeAgentMarker
    $occupiedTargets = @($claudeTargets | Where-Object { Test-Path -LiteralPath $_ })
    if (($occupiedTargets.Count -gt 0) -and ($agentOwner -ne $repoRoot) -and (-not $Force)) {
        throw "Claude agent destination is not owned by this project: $claudeAgentRoot"
    }
    $pathsToBackup += $claudeDestination
    $pathsToBackup += $claudeMarker
    $pathsToBackup += $claudeTargets
    $pathsToBackup += $claudeAgentMarker
}

$pathsToBackup = @($pathsToBackup | Select-Object -Unique)
$installedPaths = @()
$transactionCommitted = $false
try {
    foreach ($path in $pathsToBackup) { Add-TransactionBackup $path }
    if ($HostTarget -in @('codex', 'all')) {
        $installedPaths += Install-OwnedDirectory $skillSource $codexDestination
        if ($env:ONSHAPE_AGENT_TEST_FAIL_HOST -eq 'codex') { throw 'Injected host installation failure: codex' }
    }
    if ($HostTarget -in @('claude', 'all')) {
        $installedPaths += Install-OwnedDirectory $skillSource $claudeDestination
        $installedPaths += Install-ClaudeAgents $ClaudeConfigDir
        if ($env:ONSHAPE_AGENT_TEST_FAIL_HOST -eq 'claude') { throw 'Injected host installation failure: claude' }
    }

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
    Write-JsonAtomic $statePath $state
    Invoke-TransactionCommit
    $transactionCommitted = $true
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
} catch {
    $failure = $_
    if (-not $transactionCommitted) {
        try { Invoke-TransactionRollback } catch { }
    }
    throw $failure
}
