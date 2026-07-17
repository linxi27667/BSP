[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Firmware,
    [Parameter(Mandatory)][string]$Device,
    [ValidateSet('SWD', 'JTAG', 'FINE')][string]$Interface = 'SWD',
    [ValidateRange(1, 50000)][int]$Speed = 4000,
    [string]$UsbSerial,
    [string]$JLinkExe,
    [Parameter(Mandatory)][string]$LogPath,
    [Parameter(Mandatory)][switch]$ConfirmOutputSafe
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmOutputSafe) { throw 'Refusing flash: ConfirmOutputSafe is required.' }
$firmwarePath = (Resolve-Path -LiteralPath $Firmware).Path
$resolvedLog = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($LogPath)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resolvedLog) | Out-Null

if (-not $JLinkExe) {
    $candidates = @('C:\Program Files\SEGGER\JLink\JLink.exe')
    $candidates += Get-ChildItem 'C:\Program Files\SEGGER' -Directory -Filter 'JLink*' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'JLink.exe' }
    $JLinkExe = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $JLinkExe -or -not (Test-Path -LiteralPath $JLinkExe)) {
    throw 'JLink.exe not found. Pass -JLinkExe explicitly.'
}

$commandFile = Join-Path ([IO.Path]::GetTempPath()) ("jlink-flash-{0}.jlink" -f [guid]::NewGuid())
try {
    @('r', 'h', "loadfile $firmwarePath", 'r', 'g', 'q') |
        Set-Content -LiteralPath $commandFile -Encoding ascii
    $arguments = @('-Device', $Device, '-If', $Interface, '-Speed', $Speed,
                   '-AutoConnect', 1, '-CommandFile', $commandFile, '-Log', $resolvedLog)
    if ($UsbSerial) { $arguments = @('-USB', $UsbSerial) + $arguments }
    Write-Host "Starting J-Link flash: $JLinkExe $($arguments -join ' ')"
    & $JLinkExe @arguments
    $text = Get-Content -Raw -LiteralPath $resolvedLog
    if ($text -notmatch 'O\.K\.' -or $text -match '(?i)verify failed|cannot connect|error:') {
        throw "J-Link program/verify did not pass. See $resolvedLog"
    }
}
finally {
    Remove-Item -LiteralPath $commandFile -Force -ErrorAction SilentlyContinue
}

Write-Host "J-Link flash verified. Log=$resolvedLog"
