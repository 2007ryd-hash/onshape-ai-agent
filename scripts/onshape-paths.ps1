# Keep setup and presence checks aligned with onshape-mcp's Windows paths.
# A rooted path such as \config or C:config is not an absolute XDG override.
function Get-OnshapeStorageRoot([switch]$Data) {
    $xdg = if ($Data) { $env:XDG_DATA_HOME } else { $env:XDG_CONFIG_HOME }
    if ($xdg -and ($xdg -match '^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/]+[\\/][^\\/]+)')) {
        return Join-Path $xdg 'onshape-mcp'
    }
    $base = if ($Data) { $env:LOCALAPPDATA } else { $env:APPDATA }
    if (-not $base) {
        $base = Join-Path $HOME $(if ($Data) { 'AppData\Local' } else { 'AppData\Roaming' })
    }
    return Join-Path $base 'onshape-mcp'
}

function Get-OnshapeConfigPath() {
    return Join-Path (Get-OnshapeStorageRoot) 'config.toml'
}

function Get-OnshapeTokenPath() {
    return Join-Path (Get-OnshapeStorageRoot -Data) 'tokens.json'
}
