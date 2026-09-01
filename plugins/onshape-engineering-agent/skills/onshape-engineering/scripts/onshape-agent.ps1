[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

$ErrorActionPreference = 'Stop'
$stateDir = if ($env:ONSHAPE_AGENT_STATE_DIR) { $env:ONSHAPE_AGENT_STATE_DIR } else { Join-Path $env:LOCALAPPDATA 'onshape-engineering-agent' }
$statePath = Join-Path $stateDir 'install.json'
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "Onshape Engineering Agent is not installed: $statePath" }
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
$pythonPath = [string]$state.python_path
$repoRoot = [string]$state.repo_root
if ([string]::IsNullOrWhiteSpace($pythonPath) -or [string]::IsNullOrWhiteSpace($repoRoot)) { throw "Onshape Engineering Agent install state is incomplete: $statePath" }
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw "Installed Python runtime is missing: $pythonPath" }
if (-not (Test-Path -LiteralPath $repoRoot -PathType Container)) { throw "Installed repository is missing: $repoRoot" }
$repoRoot = (Resolve-Path -LiteralPath $repoRoot).Path
$sourceRoot = Join-Path $repoRoot 'src'
$pathSeparator = [IO.Path]::PathSeparator
if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $sourceRoot
} elseif (($env:PYTHONPATH -split [regex]::Escape([string]$pathSeparator)) -notcontains $sourceRoot) {
    $env:PYTHONPATH = "$sourceRoot$pathSeparator$($env:PYTHONPATH)"
}
Set-Location -LiteralPath $repoRoot
& $pythonPath -m onshape_agent.cli @Arguments
exit $LASTEXITCODE
