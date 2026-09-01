[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$script:OnshapeMcpVersion = '0.5.2'
$script:OnshapeMcpPackage = 'onshape-mcp@0.5.2'

function Get-NodeCommand() {
    $command = @(Get-Command 'node.exe' -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1
    if ($null -eq $command) { $command = @(Get-Command 'node' -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1 }
    return $command
}

function Resolve-NpxCommand() {
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

$npxCommand = Resolve-NpxCommand
$loginArguments = @('--yes', $script:OnshapeMcpPackage, 'auth', 'login')
# Do not trigger login as a side effect of another command. This is the sole
# explicit OAuth entry point and child output is intentionally not forwarded.
& $npxCommand.Source @loginArguments 1>$null 2>$null
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) { throw "Explicit Onshape OAuth login failed (exit code $exitCode)" }
Write-Output 'Explicit auth login completed for onshape-mcp@0.5.2.'
