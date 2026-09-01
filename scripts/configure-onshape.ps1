[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$script:OnshapeMcpVersion = '0.5.2'
$script:OnshapeMcpPackage = 'onshape-mcp@0.5.2'
$script:OnshapeCallback = 'http://localhost:18338/callback'

function Get-NodeCommand() {
    $command = @(Get-Command 'node.exe' -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1
    if ($null -eq $command) { $command = @(Get-Command 'node' -CommandType Application -ErrorAction SilentlyContinue) | Select-Object -First 1 }
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

function ConvertTo-TomlString([string]$value) {
    $escaped = $value.Replace('\', '\\').Replace('"', '\"').Replace("`r", '\r').Replace("`n", '\n')
    return '"' + $escaped + '"'
}

function Update-AuthSection([string]$content, [string]$clientId, [string]$clientSecret, [string]$callback) {
    $lines = if ($null -eq $content -or $content.Length -eq 0) { @() } else { @($content -split "`r?`n") }
    $authStart = -1
    $authEnd = $lines.Count
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match '^\s*\[auth\]\s*$') { $authStart = $index; break }
    }
    if ($authStart -ge 0) {
        for ($index = $authStart + 1; $index -lt $lines.Count; $index++) {
            if ($lines[$index] -match '^\s*\[[^\]]+\]\s*$') { $authEnd = $index; break }
        }
        $values = @{
            'client_id' = ConvertTo-TomlString $clientId
            'client_secret' = ConvertTo-TomlString $clientSecret
            'redirect_uri' = ConvertTo-TomlString $callback
        }
        $seen = @{}
        $updated = New-Object System.Collections.Generic.List[string]
        for ($index = 0; $index -lt $lines.Count; $index++) {
            $line = [string]$lines[$index]
            if (($index -gt $authStart) -and ($index -lt $authEnd) -and ($line -match '^\s*(client_id|client_secret|redirect_uri)\s*=')) {
                $key = $Matches[1]
                if (-not $seen.ContainsKey($key)) {
                    $updated.Add("$key = $($values[$key])")
                    $seen[$key] = $true
                }
                continue
            }
            $updated.Add($line)
            if ($index -eq $authStart) {
                # Existing auth keys are inserted immediately below the section header.
                foreach ($key in @('client_id', 'client_secret', 'redirect_uri')) {
                    if (-not $seen.ContainsKey($key)) {
                        $updated.Add("$key = $($values[$key])")
                        $seen[$key] = $true
                    }
                }
            }
        }
        return ($updated -join "`n").TrimEnd("`n") + "`n"
    }

    $suffix = @(
        '',
        '[auth]',
        "client_id = $(ConvertTo-TomlString $clientId)",
        "client_secret = $(ConvertTo-TomlString $clientSecret)",
        "redirect_uri = $(ConvertTo-TomlString $callback)"
    )
    return (($lines + $suffix) -join "`n").TrimStart("`n") + "`n"
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
    # deterministic automation and turns the line into a SecureString before
    # the common BSTR conversion below.
    $plainSecret = [Console]::In.ReadLine()
    if ($null -eq $plainSecret) { return $null }
    $secure = New-Object Security.SecureString
    foreach ($character in $plainSecret.ToCharArray()) { $secure.AppendChar($character) }
    $secure.MakeReadOnly()
    return $secure
}

$null = Assert-NodeAndNpx
Write-Output 'Onshape OAuth setup'
Write-Output "Register a user-owned OAuth application with callback: $script:OnshapeCallback"
$clientId = Read-ClientId
if ([string]::IsNullOrWhiteSpace($clientId)) { throw 'Client ID cannot be empty' }
$secureSecret = Read-ClientSecret
if ($null -eq $secureSecret) { throw 'Client secret cannot be empty' }
$secretPointer = [IntPtr]::Zero
$clientSecret = $null
try {
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
    $clientSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
} finally {
    if ($secretPointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer) }
}
if ([string]::IsNullOrEmpty($clientSecret)) { throw 'Client secret cannot be empty' }

$appDataRoot = if ($env:APPDATA) { $env:APPDATA } else { Join-Path $HOME 'AppData\Roaming' }
$configDirectory = Join-Path $appDataRoot 'onshape-mcp'
$configPath = Join-Path $configDirectory 'config.toml'
New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
$existingConfig = if (Test-Path -LiteralPath $configPath -PathType Leaf) { Get-Content -Raw -LiteralPath $configPath } else { '' }
$configText = Update-AuthSection $existingConfig $clientId $clientSecret $script:OnshapeCallback
[IO.File]::WriteAllText($configPath, $configText, (New-Object Text.UTF8Encoding($false)))
$clientSecret = $null
Write-Output "OAuth configuration saved to $configPath"
Write-Output 'Next step: run scripts/login-onshape.ps1 to explicitly authorize access.'
