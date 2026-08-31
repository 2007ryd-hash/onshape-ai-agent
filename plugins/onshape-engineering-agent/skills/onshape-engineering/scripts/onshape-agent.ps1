[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

$ErrorActionPreference = 'Stop'
$stateDir = if ($env:ONSHAPE_AGENT_STATE_DIR) { $env:ONSHAPE_AGENT_STATE_DIR } else { Join-Path $env:LOCALAPPDATA 'onshape-engineering-agent' }
$statePath = Join-Path $stateDir 'install.json'
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "Onshape Engineering Agent is not installed: $statePath" }
$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $state.python_path -PathType Leaf)) { throw "Installed Python runtime is missing: $($state.python_path)" }
& $state.python_path -m onshape_agent.cli @Arguments
exit $LASTEXITCODE
