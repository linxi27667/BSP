[CmdletBinding()]
param(
    [string]$ProjectPath = (Get-Location).Path,
    [string]$IdfPath = "E:\MCU\esp32\.espressif\v5.5.3\esp-idf",
    [string]$Port,
    [int]$Baud = 115200,
    [switch]$BuildOnly,
    [switch]$Flash,
    [int]$MonitorSeconds = 0,
    [string]$LogPath
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ProjectPath)) {
    throw "ProjectPath not found: $ProjectPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $IdfPath "export.ps1"))) {
    throw "ESP-IDF export.ps1 not found: $IdfPath"
}

if (($Flash -or $MonitorSeconds -gt 0) -and -not $Port) {
    Write-Host "Serial ports:"
    try { [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object | ForEach-Object { Write-Host "  $_" } } catch {}
    throw "Port is required for flash or monitor. Ask the user which COM port to use."
}

Push-Location $ProjectPath
try {
    & (Join-Path $IdfPath "export.ps1")
    if ($LASTEXITCODE -ne 0) { throw "ESP-IDF export failed" }

    idf.py build
    if ($LASTEXITCODE -ne 0) { throw "idf.py build failed" }

    if ($BuildOnly) { return }

    if ($Flash) {
        idf.py -p $Port flash
        if ($LASTEXITCODE -ne 0) { throw "idf.py flash failed on $Port" }
    }

    if ($MonitorSeconds -gt 0) {
        if (-not $LogPath) {
            $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
            $LogPath = Join-Path $ProjectPath "logs\espidf_${Port}_$stamp.log"
        }
        $capture = Join-Path (Split-Path $PSScriptRoot -Parent) "scripts\serial-capture.py"
        python $capture --port $Port --baud $Baud --seconds $MonitorSeconds --output $LogPath
        if ($LASTEXITCODE -ne 0) { throw "serial capture failed" }
    }
}
finally {
    Pop-Location
}
