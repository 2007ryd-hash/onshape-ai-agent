[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$script:OnshapeMcpVersion = '0.5.2'
$script:OnshapeMcpPackage = 'onshape-mcp@0.5.2'
$script:OnshapeCallback = 'http://localhost:18338/callback'

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

function Resolve-InstallState() {
    $stateDir = if ($env:ONSHAPE_AGENT_STATE_DIR) {
        $env:ONSHAPE_AGENT_STATE_DIR
    } elseif ($env:LOCALAPPDATA) {
        Join-Path $env:LOCALAPPDATA 'onshape-engineering-agent'
    } else {
        Join-Path $HOME 'AppData\Local\onshape-engineering-agent'
    }
    $statePath = Join-Path $stateDir 'install.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "Onshape Engineering Agent is not installed: $statePath"
    }
    try {
        return Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    } catch {
        throw "Onshape Engineering Agent install state is invalid: $statePath"
    }
}

function Read-ClientId() {
    if ([Console]::IsInputRedirected) { return [Console]::In.ReadLine() }
    return Read-Host 'Onshape OAuth client ID'
}

function Read-ClientSecret() {
    if (-not [Console]::IsInputRedirected) {
        return Read-Host 'Onshape OAuth client secret' -AsSecureString
    }
    # Read-Host owns the interactive path. A redirected stdin path is kept for
    # deterministic automation and turns the line into a SecureString below.
    $plainSecret = [Console]::In.ReadLine()
    if ($null -eq $plainSecret) { return $null }
    $secure = New-Object Security.SecureString
    foreach ($character in $plainSecret.ToCharArray()) { $secure.AppendChar($character) }
    $secure.MakeReadOnly()
    return $secure
}

$secureSecret = $null
$secretPointer = [IntPtr]::Zero
$clientSecret = $null
$clientId = $null
$payloadJson = $null
$configText = $null
$existingConfig = $null
$state = $null
try {
    $null = Assert-NodeAndNpx
    $state = Resolve-InstallState
    $pythonPath = [string]$state.python_path
    $repoRoot = [string]$state.repo_root
    if ([string]::IsNullOrWhiteSpace($pythonPath) -or [string]::IsNullOrWhiteSpace($repoRoot)) {
        throw 'Onshape Engineering Agent install state is incomplete'
    }
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw 'Installed Python runtime is missing'
    }
    if (-not (Test-Path -LiteralPath $repoRoot -PathType Container)) {
        throw 'Installed repository is missing'
    }
    $repoRoot = (Resolve-Path -LiteralPath $repoRoot).Path
    $sourceRoot = Join-Path $repoRoot 'src'
    $pathSeparator = [IO.Path]::PathSeparator
    if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
        $env:PYTHONPATH = $sourceRoot
    } elseif (($env:PYTHONPATH -split [regex]::Escape([string]$pathSeparator)) -notcontains $sourceRoot) {
        $env:PYTHONPATH = "$sourceRoot$pathSeparator$($env:PYTHONPATH)"
    }

    Write-Output 'Onshape OAuth setup'
    Write-Output "Register a user-owned OAuth application with callback: $script:OnshapeCallback"
    $clientId = Read-ClientId
    if ([string]::IsNullOrWhiteSpace($clientId)) { throw 'Client ID cannot be empty' }
    $secureSecret = Read-ClientSecret
    if ($null -eq $secureSecret) { throw 'Client secret cannot be empty' }
    try {
        $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
        $clientSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
    } finally {
        if ($secretPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer) }
        $secretPointer = [IntPtr]::Zero
    }
    if ([string]::IsNullOrEmpty($clientSecret)) { throw 'Client secret cannot be empty' }

    $appDataRoot = if ($env:APPDATA) { $env:APPDATA } else { Join-Path $HOME 'AppData\Roaming' }
    $configPath = Join-Path $appDataRoot 'onshape-mcp\config.toml'
    $payloadJson = @{
        client_id = $clientId
        client_secret = $clientSecret
        redirect_uri = $script:OnshapeCallback
    } | ConvertTo-Json -Compress
    $payloadJson | & $pythonPath -m onshape_agent.onshape_config --config-path $configPath 1>$null 2>$null
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "Unable to update upstream Onshape configuration: $configPath" }
    Write-Output "OAuth configuration saved to $configPath"
    Write-Output 'Next step: run scripts/login-onshape.ps1 to explicitly authorize access.'
} finally {
    if ($null -ne $secureSecret) { $secureSecret.Dispose() }
    if ($secretPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer) }
    $clientSecret = $null
    $clientId = $null
    $payloadJson = $null
    $configText = $null
    $existingConfig = $null
    $state = $null
}
