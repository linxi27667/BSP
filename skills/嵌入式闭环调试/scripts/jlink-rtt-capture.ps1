[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Device,
    [ValidateSet("SWD", "JTAG", "FINE")]
    [string]$Interface = "SWD",
    [ValidateRange(1, 50000)]
    [int]$Speed = 4000,
    [ValidateRange(0, 15)]
    [int]$Channel = 0,
    [ValidateRange(1, 3600)]
    [int]$DurationSeconds = 90,
    [Parameter(Mandatory)]
    [string]$OutputPath,
    [string]$JLinkRttLogger,
    [string]$UsbSerial,
    [string]$RttAddress,
    [string]$RttSearchRanges
)

$ErrorActionPreference = "Stop"

if (-not $JLinkRttLogger) {
    $candidates = @(
        "C:\Program Files\SEGGER\JLink\JLinkRTTLogger.exe",
        "C:\Program Files (x86)\SEGGER\JLink\JLinkRTTLogger.exe"
    )
    $JLinkRttLogger = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $JLinkRttLogger -or -not (Test-Path -LiteralPath $JLinkRttLogger)) {
    throw "JLinkRTTLogger.exe not found. Pass -JLinkRttLogger with its executable path."
}

$resolvedOutput = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
$outputDirectory = Split-Path -Parent $resolvedOutput
if ($outputDirectory) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}

$arguments = @(
    "-Device", $Device,
    "-If", $Interface,
    "-Speed", $Speed,
    "-RTTChannel", $Channel
)
if ($UsbSerial) { $arguments += @("-USB", $UsbSerial) }
if ($RttAddress) { $arguments += @("-RTTAddress", $RttAddress) }
if ($RttSearchRanges) { $arguments += @("-RTTSearchRanges", "`"$RttSearchRanges`"") }
$arguments += $resolvedOutput

Write-Host "Starting CLI RTT capture: $JLinkRttLogger $($arguments -join ' ')"
$process = Start-Process -FilePath $JLinkRttLogger -ArgumentList $arguments -PassThru -NoNewWindow
try {
    if (-not $process.WaitForExit($DurationSeconds * 1000)) {
        Stop-Process -Id $process.Id -ErrorAction Stop
        $process.WaitForExit()
    }
} finally {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $resolvedOutput)) {
    throw "RTT logger did not create the output file: $resolvedOutput"
}

Get-Item -LiteralPath $resolvedOutput | Select-Object FullName, Length, LastWriteTime
