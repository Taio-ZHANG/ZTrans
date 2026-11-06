param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\ZTrans'),
    [switch]$DesktopShortcut,
    [switch]$StartAtLogin
)
$ErrorActionPreference = 'Stop'
$payload = Join-Path $PSScriptRoot 'dist\ZTrans'
if (-not (Test-Path -LiteralPath (Join-Path $payload 'ZTrans.exe'))) {
    throw 'Build ZTrans first with build.ps1.'
}
if (Test-Path -LiteralPath $Destination) { throw 'Destination exists; choose a new folder.' }
New-Item -ItemType Directory -Path $Destination | Out-Null
Copy-Item -Path (Join-Path $payload '*') -Destination $Destination -Recurse
$shell = New-Object -ComObject WScript.Shell
if ($DesktopShortcut) {
    $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'ZTrans.lnk'))
    $shortcut.TargetPath = Join-Path $Destination 'ZTrans.exe'
    $shortcut.WorkingDirectory = $Destination
    $shortcut.Save()
}
if ($StartAtLogin) {
    $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'ZTrans.lnk'))
    $shortcut.TargetPath = Join-Path $Destination 'ZTrans.exe'
    $shortcut.Arguments = '--tray'
    $shortcut.WorkingDirectory = $Destination
    $shortcut.Save()
}
Write-Output "Installed: $Destination"
